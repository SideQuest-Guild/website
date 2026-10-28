"""Raid, signup, and raid-chart schemas.

``class`` is a Python keyword, so the Python-side attribute is ``wow_class``; ``Field(alias=...)`` maps it to the
wire name ``class`` in both directions. ``populate_by_name=True`` lets services also construct instances with the
``wow_class=`` keyword.
"""

from datetime import datetime  # pydantic needs it at runtime
from enum import StrEnum
from typing import Literal
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SignupRole(StrEnum):
    """What role a signed-up character plays."""

    TANK = "tank"
    HEALER = "healer"
    DPS = "dps"


class SignupStatus(StrEnum):
    """Whether a member is coming."""

    SIGNED = "signed"
    TENTATIVE = "tentative"
    ABSENT = "absent"


class RaidStatus(StrEnum):
    """Lifecycle of a scheduled raid."""

    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class WowClass(StrEnum):
    """Playable WoW classes."""

    WARRIOR = "warrior"
    PALADIN = "paladin"
    HUNTER = "hunter"
    ROGUE = "rogue"
    PRIEST = "priest"
    SHAMAN = "shaman"
    MAGE = "mage"
    WARLOCK = "warlock"
    DRUID = "druid"


RaidSize = Literal[10, 20, 40]


class RaidCounts(BaseModel):
    """Headcounts for a raid. ``tank``/``healer``/``dps`` only count ``signed`` signups."""

    tank: int
    healer: int
    dps: int
    tentative: int
    absent: int


class RaidSummary(BaseModel):
    """One raid as returned in list views. ``instance`` is ``""`` and ``size`` ``None`` for Discord-created events."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    instance: str
    starts_at: datetime
    ends_at: datetime | None
    size: int | None
    status: RaidStatus
    notes: str | None
    counts: RaidCounts


class SignupMember(BaseModel):
    """The public-facing slice of a signed-up member."""

    model_config = ConfigDict(from_attributes=True)

    display_name: str
    avatar_url: str | None


class Signup(BaseModel):
    """One member's signup for a raid, including the officer-assigned raid chart slot."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    id: UUID
    member: SignupMember
    character: str
    wow_class: WowClass = Field(alias="class")
    role: SignupRole
    status: SignupStatus
    comment: str | None
    group: int | None
    bench: bool
    updated_at: datetime


class RaidDetail(RaidSummary):
    """A single raid with its full roster."""

    signups: list[Signup]
    my_signup: Signup | None


class RaidCreate(BaseModel):
    """Body for ``POST /api/raids`` (officer)."""

    title: str = Field(min_length=1, max_length=200)
    instance: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime | None = None
    size: RaidSize
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _ends_after_start(self) -> RaidCreate:
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            msg = "ends_at must be after starts_at"
            raise ValueError(msg)
        return self


class RaidUpdate(BaseModel):
    """Body for ``PATCH /api/raids/{id}`` (officer). Only present fields change; ``ends_at: null`` clears the end.

    ``ends_at`` vs ``starts_at`` is checked against the stored raid by the service when only one of them is sent.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    instance: str | None = Field(default=None, min_length=1, max_length=200)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    size: RaidSize | None = None
    notes: str | None = Field(default=None, max_length=2000)
    status: RaidStatus | None = None


class SignupUpsert(BaseModel):
    """Body for ``PUT /api/raids/{id}/signup`` (member)."""

    model_config = ConfigDict(populate_by_name=True)

    character: str = Field(min_length=1, max_length=24)
    wow_class: WowClass = Field(alias="class")
    role: SignupRole
    status: SignupStatus
    comment: str | None = Field(default=None, max_length=200)


class RaidChartUpdate(BaseModel):
    """Body for ``PATCH /api/raids/{id}/signups/{signup_id}`` (officer): place a signed player on the chart."""

    group: int | None = Field(default=None, ge=1, le=8)
    bench: bool | None = None
