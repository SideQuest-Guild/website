"""Gear-swap sims through wowsims/forever: the bot's ``#sim`` forum request and result shapes.

A member names a character and up to 6 gear swaps; the API queues a sim job (``SimJob`` holds its own worn gear
``wearing`` corrections, since Battle.net's copy of a character's gear is stale until it next logs out), runs
``wowsimcli`` once per job, and returns one ``SimComparison`` per combination of swaps applied, each with one
``SimRow`` per (targets, mob) scenario the request asked for.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SIM_SLOTS = (
    "head",
    "neck",
    "shoulder",
    "back",
    "chest",
    "wrist",
    "hands",
    "waist",
    "legs",
    "feet",
    "finger1",
    "finger2",
    "trinket1",
    "trinket2",
    "main_hand",
    "off_hand",
    "ranged",
)
SIM_MOB_TYPES = ("humanoid", "undead", "beast", "demon", "dragonkin", "elemental", "giant", "mechanical")
MAX_SIM_SWAPS = 6
MAX_SIM_WEARING = 17
MAX_QUEUED_SIM_JOBS = 3
SIM_JOB_RETENTION_DAYS = 7
SimSlot = Literal[
    "head",
    "neck",
    "shoulder",
    "back",
    "chest",
    "wrist",
    "hands",
    "waist",
    "legs",
    "feet",
    "finger1",
    "finger2",
    "trinket1",
    "trinket2",
    "main_hand",
    "off_hand",
    "ranged",
]
SimMobType = Literal["humanoid", "undead", "beast", "demon", "dragonkin", "elemental", "giant", "mechanical"]
SimRole = Literal["tank", "healer", "dps"]
SimJobStatusName = Literal["queued", "running", "done", "failed"]


class SimItem(BaseModel):
    """One item to try (a swap) or correct the baseline with (``wearing``)."""

    item: str = Field(
        description="The item's numeric game id, a wowhead URL containing `item=<id>`, or its name (case-insensitive)."
    )
    slot: SimSlot | None = Field(
        default=None,
        description=(
            "The slot to put the item in. Required unless the item only fits one slot; a ring or trinket with no "
            "slot is tried in both of its slots as separate comparisons."
        ),
    )
    enchant: str | None = Field(default=None, description="An enchant name to apply to the item.")
    suffix: str | None = Field(default=None, description="A random-suffix name (e.g. 'of the Bear') on the item.")


class SimRequest(BaseModel):
    """Body for ``POST /api/guilds/{guild_id}/sims``."""

    character: str = Field(description="The character's 'Name Surname' or slug, e.g. 'legs-behindhead'.")
    swaps: list[SimItem] = Field(min_length=1, max_length=MAX_SIM_SWAPS, description="The items to try, up to 6.")
    wearing: list[SimItem] = Field(
        default_factory=list,
        max_length=MAX_SIM_WEARING,
        description=(
            "Corrections to the character's stored gear, since Battle.net's copy is stale until the character "
            "next logs out."
        ),
    )
    spec: str | None = Field(
        default=None,
        description="Override the character's spec, e.g. 'feralbear' for a druid tanking instead of cat form.",
    )
    talents: str | None = Field(
        default=None, description="A wowhead-style talent string; defaults to the spec preset's own talents."
    )
    targets: list[int] = Field(
        default_factory=lambda: [1, 4], description="Target counts to sim, each 1-5 (default 1 and 4)."
    )
    mobs: list[SimMobType] = Field(default_factory=lambda: ["humanoid"], description="Mob types to sim against.")
    duration: int = Field(default=90, ge=30, le=300, description="Fight length in seconds.")
    requested_by: str | None = Field(default=None, description="The requesting Discord user's id, for rate limiting.")


class SimMetrics(BaseModel):
    """One scenario's measured metrics. A metric a spec doesn't produce (e.g. ``hps`` for a dps spec) is `None`."""

    dps: float | None = None
    tps: float | None = None
    dtps: float | None = None
    hps: float | None = None


class ItemRef(BaseModel):
    """An item as a changed-gear line names it."""

    id: int = Field(description="The item's game id.")
    name: str = Field(description="The item's display name.")


class GearChange(BaseModel):
    """One slot changed between a comparison's baseline and swapped gear."""

    slot: SimSlot = Field(description="The slot that changed.")
    from_item: ItemRef | None = Field(default=None, description="What was in the slot before, if anything.")
    to_item: ItemRef = Field(description="What's in the slot now.")


class SimRow(BaseModel):
    """One (targets, mob) scenario's baseline vs. swapped metrics."""

    targets: int = Field(description="How many targets this scenario simmed against.")
    mob: SimMobType = Field(description="The mob type this scenario simmed against.")
    baseline: SimMetrics = Field(description="Metrics with the character's current gear.")
    swapped: SimMetrics = Field(description="Metrics with this comparison's gear changes applied.")
    delta_pct: SimMetrics = Field(description="Percent change from baseline to swapped, per metric.")
    noise: list[str] = Field(
        default_factory=list, description="Metric names whose delta is within two standard errors of zero."
    )


class SimComparison(BaseModel):
    """One combination of swaps applied, across every requested scenario."""

    label: str = Field(description="What changed, e.g. 'main_hand: Eater of the Dead -> Blade of Necromancy'.")
    changes: list[GearChange] = Field(description="The gear changes this comparison applied.")
    rows: list[SimRow] = Field(description="One row per requested (targets, mob) scenario.")


class SimResult(BaseModel):
    """What a finished sim job found."""

    character: str = Field(description="The character's 'Name Surname'.")
    class_name: str = Field(description="The character's class.")
    spec: str = Field(description="The spec simmed, e.g. 'protection'.")
    role: SimRole = Field(description="The spec's role: tank, healer, or dps.")
    level: int = Field(description="The character's level (the sim only models level 60).")
    gear_fetched_at: datetime | None = Field(
        default=None, description="When the character's gear was last fetched from Battle.net."
    )
    iterations: int = Field(description="Sim iterations run per scenario.")
    duration: int = Field(description="Fight length in seconds.")
    comparisons: list[SimComparison] = Field(description="One comparison per combination of swaps applied.")
    notes: list[str] = Field(
        default_factory=list,
        description="Things the sim skipped or approximated, such as an enchant with no sim equivalent.",
    )


class SimJobSchema(BaseModel):
    """A sim job's status, and its result once done."""

    id: UUID = Field(description="The job's id.")
    status: SimJobStatusName = Field(description="queued, running, done, or failed.")
    position: int | None = Field(
        default=None, description="This job's place in the queue, counting other queued jobs ahead of it."
    )
    error: str | None = Field(default=None, description="A plain-English failure reason, if status is failed.")
    result: SimResult | None = Field(default=None, description="The sim result, once status is done.")
    created_at: datetime = Field(description="When the job was queued.")
