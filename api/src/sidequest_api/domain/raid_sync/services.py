"""Desired-state computation and Discord-state application for the raid <-> Discord sync.

See ``local://raid-sync-contract.md`` (recorded in the PR/task description) for the full wire contract. In short:
the API decides what Discord should show (``DiscordEventPush``, polled via ``list_pending``) and the bot reports
back what Discord actually holds (``DiscordEventState``, applied via ``apply_event_state``/``reconcile``). Hash
columns on ``Raid`` (``discord_pushed_hash``, ``discord_seen_hash``) keep the two sides from echoing each other.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from sidequest_api.domain.raids.services import RaidsService
from sidequest_common.models import DiscordEventTombstone, Raid
from sidequest_common.schemas import (
    DiscordEventPush,
    DiscordEventReconcile,
    DiscordEventState,
    DiscordEventStatus,
    DiscordPushAck,
    DiscordSyncPending,
    PushAction,
    RaidCounts,
)

FOOTER_HEADER = "── SideQuest raid ──"
MAX_DESCRIPTION_LENGTH = 1000
DEFAULT_DURATION = timedelta(hours=3)
_SIGN_UP_PATH = "/raids/event/?id="
_ACTION_BY_STATUS: dict[str, PushAction] = {"scheduled": "upsert", "cancelled": "cancel", "completed": "complete"}
_ENDED_IN_DISCORD = (DiscordEventStatus.CANCELLED, DiscordEventStatus.COMPLETED)


def _truncate(text: str, limit: int) -> str:
    """``text`` cut to ``limit`` chars, with a trailing "…" if it was cut."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    return text[: limit - 1] + "…"


def _build_footer(raid: Raid, counts: RaidCounts, web_base_url: str) -> str:
    lines = [FOOTER_HEADER]
    parts = []
    if raid.instance:
        parts.append(raid.instance)
    if raid.size is not None:
        parts.append(f"{raid.size}-player")
    if parts:
        lines.append(" · ".join(parts))
    signed = f"Signed: {counts.tank} tanks · {counts.healer} healers · {counts.dps} dps"
    if counts.tentative > 0:
        signed += f" · {counts.tentative} tentative"
    lines.append(signed)
    lines.append(f"Sign up: {web_base_url}{_SIGN_UP_PATH}{raid.id}")
    return "\n".join(lines)


def _build_description(raid: Raid, footer: str) -> str:
    if not raid.notes:
        return footer
    budget = max(MAX_DESCRIPTION_LENGTH - len(footer) - 2, 0)
    notes = _truncate(raid.notes, budget)
    if not notes:
        return footer
    return f"{notes}\n\n{footer}"


def _strip_footer(description: str | None) -> str | None:
    """``description`` with the footer (and the blank line before it, if any) removed."""
    if not description:
        return None
    index = description.find(FOOTER_HEADER)
    notes = description if index == -1 else description[:index]
    notes = notes.strip()
    return notes or None


def _extract_linked_raid_id(description: str | None) -> UUID | None:
    """The raid id in the footer's "Sign up" link, if ``description`` has one."""
    if not description:
        return None
    index = description.find(_SIGN_UP_PATH)
    if index == -1:
        return None
    start = index + len(_SIGN_UP_PATH)
    end = start + 36
    try:
        return UUID(description[start:end])
    except ValueError:
        return None


def _push_hash(
    *, action: str, name: str, description: str, location: str, starts_at: datetime, ends_at: datetime
) -> str:
    payload = json.dumps(
        [
            action,
            name,
            description,
            location,
            starts_at.astimezone(UTC).isoformat(),
            ends_at.astimezone(UTC).isoformat(),
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _state_hash(state: DiscordEventState) -> str:
    normalized = state.model_copy(
        update={
            "starts_at": state.starts_at.astimezone(UTC),
            "ends_at": state.ends_at.astimezone(UTC) if state.ends_at is not None else None,
        }
    )
    return hashlib.sha256(normalized.model_dump_json().encode()).hexdigest()


def _desired_state(raid: Raid, counts: RaidCounts, web_base_url: str) -> DiscordEventPush:
    footer = _build_footer(raid, counts, web_base_url)
    description = _build_description(raid, footer)
    name = raid.title[:100]
    location = (raid.instance or "World of Warcraft")[:100]
    ends_at = raid.ends_at or (raid.starts_at + DEFAULT_DURATION)
    action = _ACTION_BY_STATUS[raid.status]
    push_hash = _push_hash(
        action=action, name=name, description=description, location=location, starts_at=raid.starts_at, ends_at=ends_at
    )
    return DiscordEventPush(
        raid_id=raid.id,
        discord_event_id=raid.discord_event_id,
        action=action,
        name=name,
        description=description,
        location=location,
        starts_at=raid.starts_at,
        ends_at=ends_at,
        push_hash=push_hash,
    )


def _apply_discord_fields(raid: Raid, state: DiscordEventState, seen_hash: str) -> None:
    raid.title = state.name
    raid.notes = _strip_footer(state.description)
    raid.starts_at = state.starts_at
    raid.ends_at = state.ends_at
    if state.location:
        raid.instance = state.location
    if state.status in (DiscordEventStatus.SCHEDULED, DiscordEventStatus.ACTIVE):
        raid.status = "scheduled"
    elif state.status == DiscordEventStatus.CANCELLED:
        raid.status = "cancelled"
        raid.discord_event_id = None
    elif state.status == DiscordEventStatus.COMPLETED:
        raid.status = "completed"
        raid.discord_event_id = None
    raid.discord_seen_hash = seen_hash


class RaidSyncService(RaidsService):
    """Computes desired Discord state for raids and applies Discord-reported state back onto them.

    Subclasses ``RaidsService`` (same repository/model) to reuse raid lookups and ``_counts_for`` for the
    footer's "Signed" line.
    """

    async def list_pending(self, web_base_url: str) -> DiscordSyncPending:
        """Every raid whose desired Discord state is out of date, plus the tombstoned (deleted) event ids."""
        session = self.repository.session
        now = datetime.now(UTC)
        raids = list((await session.execute(select(Raid))).scalars().all())
        counts = await self._counts_for([raid.id for raid in raids])
        pushes = []
        for raid in raids:
            push = _desired_state(raid, counts[raid.id], web_base_url)
            if push.push_hash == raid.discord_pushed_hash:
                continue
            linked = raid.discord_event_id is not None
            if push.action == "upsert":
                if not linked and raid.starts_at <= now:
                    continue
            elif not linked:
                continue
            pushes.append(push)
        tombstone_ids = list((await session.execute(select(DiscordEventTombstone.discord_event_id))).scalars().all())
        return DiscordSyncPending(pushes=pushes, deletions=tombstone_ids)

    async def ack(self, raid_id: UUID, data: DiscordPushAck) -> None:
        """Record that the bot applied ``data.push_hash``, linking/unlinking per ``data.event``.

        If the raid was deleted on the site between the push and the ack, tombstone ``data.event`` instead (the
        bot still has to clean it up in Discord).
        """
        raid = await self.get_one_or_none(id=raid_id)
        if raid is None:
            if data.event is not None:
                await self._tombstone(data.event.id)
            return
        raid.discord_pushed_hash = data.push_hash
        if data.event is not None:
            raid.discord_event_id = data.event.id
            raid.discord_seen_hash = _state_hash(data.event)
        else:
            raid.discord_event_id = None
            raid.discord_seen_hash = None
        await self.update(raid, auto_commit=True)

    async def apply_event_state(self, state: DiscordEventState) -> None:
        """Apply one Discord-reported event state: find/adopt/create the raid, then sync fields unless it's our echo."""
        seen_hash = _state_hash(state)
        raid = await self.get_one_or_none(discord_event_id=state.id)
        if raid is None:
            raid = await self._adopt_or_create(state)
            if raid is None:
                return
        if raid.discord_seen_hash == seen_hash:
            return
        _apply_discord_fields(raid, state, seen_hash)
        await self.update(raid, auto_commit=True)

    async def handle_deleted_event(self, event_id: int) -> None:
        """A Discord event is gone (explicit delete, or missing from a reconcile): unlink and cancel if scheduled."""
        raid = await self.get_one_or_none(discord_event_id=event_id)
        if raid is None:
            return
        raid.discord_event_id = None
        raid.discord_pushed_hash = None
        raid.discord_seen_hash = None
        if raid.status == "scheduled":
            raid.status = "cancelled"
        await self.update(raid, auto_commit=True)

    async def delete_tombstone(self, event_id: int) -> None:
        """The bot deleted this event in Discord; drop the tombstone row. Idempotent."""
        session = self.repository.session
        tombstone = (
            await session.execute(
                select(DiscordEventTombstone).where(DiscordEventTombstone.discord_event_id == event_id)
            )
        ).scalar_one_or_none()
        if tombstone is None:
            return
        await session.delete(tombstone)
        await session.commit()

    async def reconcile(self, data: DiscordEventReconcile) -> None:
        """Apply every listed event, then treat missing linked raids as deleted and drop stale tombstones."""
        session = self.repository.session
        for state in data.events:
            await self.apply_event_state(state)
        listed_ids = {state.id for state in data.events}
        linked_raids = list(
            (await session.execute(select(Raid).where(Raid.discord_event_id.is_not(None)))).scalars().all()
        )
        for raid in linked_raids:
            if raid.discord_event_id not in listed_ids:
                await self.handle_deleted_event(raid.discord_event_id)
        tombstones = list((await session.execute(select(DiscordEventTombstone))).scalars().all())
        for tombstone in tombstones:
            if tombstone.discord_event_id not in listed_ids:
                await session.delete(tombstone)
        await session.commit()

    async def _adopt_or_create(self, state: DiscordEventState) -> Raid | None:
        """Link an unlinked raid via the footer's link, ignore a copy of an already-linked raid, or create one."""
        linked_id = _extract_linked_raid_id(state.description)
        if linked_id is not None:
            candidate = await self.get_one_or_none(id=linked_id)
            if candidate is not None:
                if candidate.discord_event_id is not None:
                    return None
                candidate.discord_event_id = state.id
                return await self.update(candidate, auto_commit=True)
        if state.status in _ENDED_IN_DISCORD:
            return None
        raid = Raid(
            title=state.name,
            instance=state.location or "",
            starts_at=state.starts_at,
            ends_at=state.ends_at,
            size=None,
            status="scheduled",
            notes=_strip_footer(state.description),
            discord_event_id=state.id,
        )
        return await self.create(raid, auto_commit=True)

    async def _tombstone(self, event_id: int) -> None:
        session = self.repository.session
        existing = (
            await session.execute(
                select(DiscordEventTombstone).where(DiscordEventTombstone.discord_event_id == event_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(DiscordEventTombstone(discord_event_id=event_id))
            await session.commit()
