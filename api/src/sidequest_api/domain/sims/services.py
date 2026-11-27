"""Sim job domain service: validates a request, queues it, reports its status, and (for the runner) executes it.

Validation (:func:`prepare_sim`) never shells out to ``wowsimcli``: it only reads the wowsims checkout's static
``names.json``/``db.json`` and the character's stored Battle.net sheet, so a bad request 400s immediately from the
request handler. Only :meth:`SimsService.run` (called by the background runner) builds SIML and runs the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_429_TOO_MANY_REQUESTS
from sqlalchemy import func, select

from sidequest_api.domain.sims import engine
from sidequest_common.models import SimJob
from sidequest_common.schemas import (
    MAX_QUEUED_SIM_JOBS,
    GearChange,
    ItemRef,
    SimComparison,
    SimItem,
    SimJobSchema,
    SimMetrics,
    SimRequest,
    SimResult,
    SimRow,
)
from sidequest_common.schemas.characters import CharacterSheet, canonical_character_name

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession
    from wow import AsyncClient

    from sidequest_api.domain.characters.services import CharactersService
    from sidequest_common.schemas import SimMobType, SimRole, SimSlot

RATE_LIMIT_MESSAGE = "You already have {count} sims queued or running; wait for one to finish first."


@dataclass
class _PlanComparison:
    label: str
    changes: list[GearChange]
    gear: dict[SimSlot, engine.GearEntry]


@dataclass
class PreparedSim:
    """A validated, ready-to-run sim: the character, its role, baseline gear, and the comparisons to try."""

    character_name: str
    class_name: str
    spec: str
    role: SimRole
    race: str
    level: int
    talents_override: str | None
    gear_fetched_at: datetime | None
    comparisons: list[_PlanComparison]
    baseline: dict[SimSlot, engine.GearEntry]
    notes: list[str] = field(default_factory=list)


async def _fetch_character_sheet(
    character: str, characters_service: CharactersService, game_data: AsyncClient
) -> tuple[str, str, str | None, str, int, CharacterSheet, datetime | None]:
    """``(display_name, class_name, battlenet_spec, race, level, sheet, fetched_at)`` for a name/slug."""
    slug = canonical_character_name(character).lower()
    try:
        row = await characters_service.get_character(slug, game_data)
    except NotFoundException as exc:
        msg = f"unknown character: {character}"
        raise engine.SimEngineError(msg) from exc
    if not row.wow_class:
        msg = f"{character} has no class on file yet; Battle.net hasn't published a profile for it"
        raise engine.SimEngineError(msg)
    sheet = CharacterSheet.model_validate(row.sheet) if row.sheet else None
    if sheet is None:
        msg = f"{character} has no character sheet yet; Battle.net hasn't published a profile for it"
        raise engine.SimEngineError(msg)
    display_name = f"{row.name} {row.surname}"
    return display_name, row.wow_class.lower(), row.spec, row.race or "Human", row.level, sheet, row.fetched_at


def _apply_wearing(
    baseline: dict[SimSlot, engine.GearEntry], wearing: Sequence[SimItem], item_db: engine.ItemDB
) -> list[str]:
    notes: list[str] = []
    for item in wearing:
        resolved = engine.resolve_sim_item(item, item_db)
        notes.extend(resolved.notes)
        slot = resolved.candidate_slots[0]
        if not item.slot and len(resolved.candidate_slots) > 1:
            msg = f"{item.item} (in wearing) needs a slot: it fits {' or '.join(resolved.candidate_slots)}"
            raise engine.SimEngineError(msg)
        baseline[slot] = resolved.entry
    return notes


def _item_ref(entry: engine.GearEntry) -> ItemRef:
    return ItemRef(id=entry.item_id, name=entry.display_name or entry.name)


def _change_label(slot: SimSlot, before: engine.GearEntry | None, after: engine.GearEntry) -> str:
    before_label = (before.display_name or before.name) if before and before.name else "(empty)"
    return f"{slot}: {before_label} -> {after.display_name or after.name}"


def _build_comparisons(
    baseline: dict[SimSlot, engine.GearEntry], resolved_swaps: list[engine.ResolvedSwap]
) -> list[_PlanComparison]:
    """The gear sets to compare against the baseline.

    All single-slot swaps go together; a ring/trinket swap with no slot is tried in each of its slots (2), one
    comparison each, capped at :data:`engine.MAX_COMPARISONS` total.
    """
    fixed_slots: dict[SimSlot, engine.GearEntry] = {}
    ambiguous: list[engine.ResolvedSwap] = []
    for swap in resolved_swaps:
        if len(swap.candidate_slots) == 1:
            fixed_slots[swap.candidate_slots[0]] = swap.entry
        else:
            ambiguous.append(swap)

    def one_comparison(extra: dict[SimSlot, engine.GearEntry]) -> _PlanComparison:
        gear = {**baseline, **fixed_slots, **extra}
        changes: list[GearChange] = []
        for slot, entry in {**fixed_slots, **extra}.items():
            before = baseline.get(slot)
            changes.append(
                GearChange(
                    slot=slot,
                    from_item=_item_ref(before) if before and before.name else None,
                    to_item=_item_ref(entry),
                )
            )
        label = ", ".join(
            _change_label(slot, baseline.get(slot), entry) for slot, entry in {**fixed_slots, **extra}.items()
        )
        return _PlanComparison(label=label, changes=changes, gear=gear)

    if not ambiguous:
        return [one_comparison({})]

    comparisons: list[_PlanComparison] = []
    # One swap's slot choice varies per comparison; any other ambiguous swap keeps its first candidate slot, so the
    # total never exceeds MAX_COMPARISONS even with several ambiguous items.
    for swap in ambiguous[:1]:
        for slot in swap.candidate_slots[: engine.MAX_AMBIGUOUS_PER_ITEM]:
            extra = {slot: swap.entry}
            for other in ambiguous[1:]:
                extra[other.candidate_slots[0]] = other.entry
            comparisons.append(one_comparison(extra))
    return comparisons[: engine.MAX_COMPARISONS]


async def prepare_sim(
    request: SimRequest, *, characters_service: CharactersService, game_data: AsyncClient, wowsims_dir: Path
) -> PreparedSim:
    """Validate ``request`` end to end and build its comparison plan. Raises :class:`engine.SimEngineError`."""
    display_name, class_name, battlenet_spec, race, level, sheet, fetched_at = await _fetch_character_sheet(
        request.character, characters_service, game_data
    )
    spec = engine.normalize_spec(class_name, battlenet_spec, request.spec)
    role = engine.role_for(class_name, spec)
    engine.check_simmable(class_name, spec, level)

    item_db = engine.item_db(wowsims_dir)
    baseline, notes = engine.gear_from_sheet(sheet, item_db)
    notes = [*notes, *_apply_wearing(baseline, request.wearing, item_db)]
    resolved_swaps = [engine.resolve_sim_item(item, item_db) for item in request.swaps]
    for swap in resolved_swaps:
        notes.extend(swap.notes)
    comparisons = _build_comparisons(baseline, resolved_swaps)
    if not request.talents:
        notes.append(f"Talents: the sim's default {spec} build; Battle.net doesn't publish your talent ranks")
    if level < engine.SIM_LEVEL:
        notes.append(f"Simmed as level {engine.SIM_LEVEL}; at {level}, read the changes as relative, not exact")

    return PreparedSim(
        character_name=display_name,
        class_name=class_name,
        spec=spec,
        role=role,
        race=race,
        level=level,
        talents_override=request.talents,
        gear_fetched_at=fetched_at,
        comparisons=comparisons,
        baseline=baseline,
        notes=notes,
    )


async def run_sim(prepared: PreparedSim, request: SimRequest, *, wowsims_dir: Path, wowsimcli: Path) -> SimResult:
    """Run every comparison's every scenario through ``wowsimcli`` and assemble the result."""
    preset = await engine.load_spec_preset(wowsims_dir, wowsimcli, prepared.class_name, prepared.spec)
    talents = prepared.talents_override or preset.talents
    scenario_list = engine.scenarios(request.targets, request.mobs)

    def siml_for(gear: dict[SimSlot, engine.GearEntry], targets: int, mob: SimMobType) -> str:
        return engine.build_siml(
            class_name=prepared.class_name,
            spec=prepared.spec,
            race=prepared.race,
            talents=talents,
            rotation=preset.rotation,
            gear=gear,
            targets=targets,
            mob=mob,
            duration=request.duration,
            role=prepared.role,
        )

    # The baseline is the same for every comparison: run it once per scenario, not once per comparison.
    baseline_players = {
        (targets, mob): await engine.run_scenario(wowsimcli, siml_for(prepared.baseline, targets, mob), wowsims_dir)
        for targets, mob in scenario_list
    }
    comparison_results: list[SimComparison] = []
    for comparison in prepared.comparisons:
        rows: list[SimRow] = []
        for targets, mob in scenario_list:
            swapped_player = await engine.run_scenario(wowsimcli, siml_for(comparison.gear, targets, mob), wowsims_dir)
            rows.append(_sim_row(targets, mob, baseline_players[(targets, mob)], swapped_player, prepared.role))
        comparison_results.append(SimComparison(label=comparison.label, changes=comparison.changes, rows=rows))

    return SimResult(
        character=prepared.character_name,
        class_name=prepared.class_name,
        spec=prepared.spec,
        role=prepared.role,
        level=prepared.level,
        gear_fetched_at=prepared.gear_fetched_at,
        iterations=engine.SIM_ITERATIONS,
        duration=request.duration,
        comparisons=comparison_results,
        notes=prepared.notes,
    )


def _sim_row(targets: int, mob: SimMobType, baseline: dict, swapped: dict, role: SimRole) -> SimRow:
    base = engine.metrics_from_player(baseline, role)
    swap = engine.metrics_from_player(swapped, role)
    noise = []
    delta: dict[str, float | None] = {}
    for metric in ("dps", "tps", "dtps", "hps"):
        delta[metric] = engine.delta_pct(base[metric], swap[metric])
        if engine.is_noise(base[metric], swap[metric], base["_sd"][metric], swap["_sd"][metric], engine.SIM_ITERATIONS):
            noise.append(metric)
    return SimRow(
        targets=targets,
        mob=mob,
        baseline=SimMetrics(dps=base["dps"], tps=base["tps"], dtps=base["dtps"], hps=base["hps"]),
        swapped=SimMetrics(dps=swap["dps"], tps=swap["tps"], dtps=swap["dtps"], hps=swap["hps"]),
        delta_pct=SimMetrics(**delta),
        noise=noise,
    )


class SimsService:
    """Queues sim jobs and reports their status; the background runner uses the free functions above to run one."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def queue(
        self, request: SimRequest, *, characters_service: CharactersService, game_data: AsyncClient, wowsims_dir: Path
    ) -> SimJobSchema:
        """Validate and queue ``request``. Raises an ``HTTPException`` (400 validation, 429 rate limit)."""
        if request.requested_by:
            pending = await self._session.scalar(
                select(func.count())
                .select_from(SimJob)
                .where(SimJob.requested_by == request.requested_by, SimJob.status.in_(("queued", "running")))
            )
            if pending and pending >= MAX_QUEUED_SIM_JOBS:
                raise HTTPException(
                    status_code=HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMIT_MESSAGE.format(count=pending)
                )
        try:
            await prepare_sim(
                request, characters_service=characters_service, game_data=game_data, wowsims_dir=wowsims_dir
            )
        except engine.SimEngineError as exc:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        job = SimJob(request=request.model_dump(mode="json"), status="queued", requested_by=request.requested_by)
        self._session.add(job)
        await self._session.flush()
        await self._session.commit()
        return await self.get(job.id)

    async def get(self, job_id: UUID) -> SimJobSchema:
        """The job, with its place in the queue while it waits; 404 if it doesn't exist (or was cleaned up)."""
        job = await self._session.get(SimJob, job_id)
        if job is None:
            msg = f"No sim job {job_id}"
            raise NotFoundException(msg)
        position = None
        if job.status == "queued":
            position = await self._session.scalar(
                select(func.count())
                .select_from(SimJob)
                .where(SimJob.status == "queued", SimJob.created_at < job.created_at)
            )
        return SimJobSchema(
            id=job.id,
            status=job.status,  # type: ignore[arg-type]
            position=position,
            error=job.error,
            result=SimResult.model_validate(job.result) if job.result else None,
            created_at=job.created_at,
        )
