"""Guild event, signup, and raid-chart schemas.

``class`` is a Python keyword, so the Python-side attribute is ``wow_class``; ``Field(alias=...)`` maps it to the
wire name ``class`` in both directions. ``populate_by_name=True`` lets services also construct instances with the
``wow_class=`` keyword.
"""

import re
from datetime import date, datetime  # pydantic needs them at runtime
from enum import StrEnum
from uuid import UUID  # pydantic needs it at runtime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventKind(StrEnum):
    """What kind of guild event this is. ``raid``/``dungeon`` are "role kinds": sign-ups need character/class/role."""

    RAID = "raid"
    DUNGEON = "dungeon"
    LEVELING = "leveling"
    PVP = "pvp"
    SOCIAL = "social"
    TRANSMOG = "transmog"
    OTHER = "other"


ROLE_KINDS = (EventKind.RAID, EventKind.DUNGEON)

EVENT_KIND_LABELS: dict[EventKind, str] = {
    EventKind.RAID: "Raid",
    EventKind.DUNGEON: "Dungeon",
    EventKind.LEVELING: "Leveling",
    EventKind.PVP: "PvP",
    EventKind.SOCIAL: "Social",
    EventKind.TRANSMOG: "Transmog",
    EventKind.OTHER: "Other",
}

EVENT_KIND_EP: dict[EventKind, int] = {
    EventKind.RAID: 10,
    EventKind.DUNGEON: 5,
    EventKind.LEVELING: 3,
    EventKind.PVP: 3,
    EventKind.SOCIAL: 2,
    EventKind.TRANSMOG: 2,
    EventKind.OTHER: 2,
}
"""EP (effort points) for attending an event of each kind, unless an officer overrides it on the event.

A raid boss kill is worth 10 EP, so these keep guild nights a small nudge next to raiding. A raid's 10 is its on-time
and full-night attendance bonus; boss kills earn their own EP on top.
"""

MAX_EVENT_EP = 50


def event_ep(kind: str, ep_override: int | None) -> int:
    """The EP an event awards: the officer's override, else its kind's preset."""
    return ep_override if ep_override is not None else EVENT_KIND_EP[EventKind(kind)]


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


class EventStatus(StrEnum):
    """Lifecycle of a scheduled guild event."""

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


class EventCounts(BaseModel):
    """Headcounts for an event. ``tank``/``healer``/``dps``/``signed`` only count ``signed`` signups.

    ``interested`` is every Discord user who clicked "Interested" on the linked Discord event, regardless of
    whether they have a site account.
    """

    tank: int
    healer: int
    dps: int
    signed: int
    tentative: int
    absent: int
    interested: int


class SeriesRef(BaseModel):
    """The minimal repeating-event schedule, attached to ``EventSummary`` for non-detached series occurrences.

    ``None`` on ``EventSummary.series`` for one-off events and occurrences an officer has edited/deleted
    individually (``series_detached``).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    weekdays: list[int]
    interval_weeks: int
    start_time: str
    timezone: str


class EventSummary(BaseModel):
    """One event as returned in list views. ``location`` is ``""`` and ``size`` ``None`` for Discord-created events.

    ``ep`` is what attending awards; ``ep_override`` is the officer-set value behind it (``None``: the kind's preset).
    ``notes``/``counts`` are ``None`` for anonymous visitors (no session, no bot ``X-API-Key``).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: EventKind
    title: str
    location: str
    starts_at: datetime
    ends_at: datetime | None
    size: int | None
    ep: int
    ep_override: int | None
    status: EventStatus
    notes: str | None
    counts: EventCounts | None
    series: SeriesRef | None


class SignupMember(BaseModel):
    """The public-facing slice of a signed-up member."""

    model_config = ConfigDict(from_attributes=True)

    display_name: str
    avatar_url: str | None


class DiscordInterest(BaseModel):
    """Discord "Interested" clicks on an event's linked Discord event. Names are never shown for non-site accounts."""

    count: int
    members: list[SignupMember]


class Signup(BaseModel):
    """One member's signup for an event, including the officer-assigned raid chart slot."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    id: UUID
    member: SignupMember
    character: str | None
    wow_class: WowClass | None = Field(alias="class")
    role: SignupRole | None
    status: SignupStatus
    comment: str | None
    group: int | None
    bench: bool
    updated_at: datetime


class EventDetail(EventSummary):
    """A single event with its full roster.

    ``signups``/``my_signup`` are empty, and ``discord_interest``/``away`` are ``None``, for anonymous visitors.
    """

    signups: list[Signup]
    my_signup: Signup | None
    discord_interest: DiscordInterest | None
    away: list[SignupMember] | None
    """Members away (see ``AwayRangeIn``) on this event's start date, America/Chicago. ``None`` if anonymous."""


class EventCreate(BaseModel):
    """Body for ``POST /api/events`` (officer)."""

    kind: EventKind
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    starts_at: datetime
    ends_at: datetime | None = None
    size: int | None = Field(default=None, ge=1, le=40)
    ep_override: int | None = Field(default=None, ge=0, le=MAX_EVENT_EP)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _ends_after_start(self) -> EventCreate:
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            msg = "ends_at must be after starts_at"
            raise ValueError(msg)
        return self


class EventUpdate(BaseModel):
    """Body for ``PATCH /api/events/{id}`` (officer). Only present fields change; ``ends_at: null`` clears the end.

    ``ep_override: null`` goes back to the kind's EP preset.

    ``ends_at`` vs ``starts_at`` is checked against the stored event by the service when only one of them is sent.
    """

    kind: EventKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    size: int | None = Field(default=None, ge=1, le=40)
    ep_override: int | None = Field(default=None, ge=0, le=MAX_EVENT_EP)
    notes: str | None = Field(default=None, max_length=2000)
    status: EventStatus | None = None


class SignupUpsert(BaseModel):
    """Body for ``PUT /api/events/{id}/signup`` (member).

    ``character``/``class``/``role`` are required (400 if missing) when the event's kind is ``raid``/``dungeon``;
    other kinds accept a bare RSVP.
    """

    model_config = ConfigDict(populate_by_name=True)

    character: str | None = Field(default=None, min_length=1, max_length=24)
    wow_class: WowClass | None = Field(default=None, alias="class")
    role: SignupRole | None = None
    status: SignupStatus
    comment: str | None = Field(default=None, max_length=200)


class ChartUpdate(BaseModel):
    """Body for ``PATCH /api/events/{id}/signups/{signup_id}`` (officer): place a signed player on the raid chart."""

    group: int | None = Field(default=None, ge=1, le=8)
    bench: bool | None = None


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_MAX_WEEKDAY = 6


def _validate_start_time(value: str) -> str:
    if not _TIME_RE.match(value):
        msg = "start_time must be HH:MM (24-hour)"
        raise ValueError(msg)
    return value


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        msg = f"Unknown timezone {value!r}"
        raise ValueError(msg) from exc
    return value


def _validate_weekdays(value: list[int]) -> list[int]:
    if not value:
        msg = "weekdays must not be empty"
        raise ValueError(msg)
    if any(day < 0 or day > _MAX_WEEKDAY for day in value):
        msg = "weekdays must be 0 (Monday) through 6 (Sunday)"
        raise ValueError(msg)
    return sorted(set(value))


class SeriesRule(BaseModel):
    """A repeating schedule rule, nested on ``EventSeriesSummary``. ``start_time`` is ``"HH:MM"`` 24-hour local time."""

    weekdays: list[int]
    interval_weeks: int
    start_time: str
    timezone: str
    duration_minutes: int | None
    starts_on: date
    until: date | None


class EventSeriesSummary(BaseModel):
    """One repeating event series, as returned by ``GET/POST/PATCH /api/event-series``.

    ``ep``/``ep_override`` as on ``EventSummary``; occurrences copy ``ep_override``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: EventKind
    title: str
    location: str
    size: int | None
    ep: int
    ep_override: int | None
    notes: str | None
    rule: SeriesRule
    active: bool
    next_starts_at: datetime | None


class EventSeriesCreate(BaseModel):
    """Body for ``POST /api/event-series`` (officer). Content and rule fields are flat (no ``rule`` nesting)."""

    kind: EventKind
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    size: int | None = Field(default=None, ge=1, le=40)
    ep_override: int | None = Field(default=None, ge=0, le=MAX_EVENT_EP)
    notes: str | None = Field(default=None, max_length=2000)
    weekdays: list[int]
    interval_weeks: int = Field(default=1)
    start_time: str
    timezone: str
    duration_minutes: int | None = Field(default=None, ge=15, le=1440)
    starts_on: date
    until: date | None = None

    @model_validator(mode="after")
    def _validate_rule(self) -> EventSeriesCreate:
        self.weekdays = _validate_weekdays(self.weekdays)
        if self.interval_weeks not in (1, 2):
            msg = "interval_weeks must be 1 or 2"
            raise ValueError(msg)
        self.start_time = _validate_start_time(self.start_time)
        self.timezone = _validate_timezone(self.timezone)
        if self.until is not None and self.until < self.starts_on:
            msg = "until must not be before starts_on"
            raise ValueError(msg)
        return self


class EventSeriesUpdate(BaseModel):
    """Body for ``PATCH /api/event-series/{id}`` (officer). Only present fields change; all are optional."""

    kind: EventKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    size: int | None = Field(default=None, ge=1, le=40)
    ep_override: int | None = Field(default=None, ge=0, le=MAX_EVENT_EP)
    notes: str | None = Field(default=None, max_length=2000)
    weekdays: list[int] | None = None
    interval_weeks: int | None = None
    start_time: str | None = None
    timezone: str | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=1440)
    starts_on: date | None = None
    until: date | None = None

    @model_validator(mode="after")
    def _validate_rule(self) -> EventSeriesUpdate:
        if self.weekdays is not None:
            self.weekdays = _validate_weekdays(self.weekdays)
        if self.interval_weeks is not None and self.interval_weeks not in (1, 2):
            msg = "interval_weeks must be 1 or 2"
            raise ValueError(msg)
        if self.start_time is not None:
            self.start_time = _validate_start_time(self.start_time)
        if self.timezone is not None:
            self.timezone = _validate_timezone(self.timezone)
        if self.until is not None and self.starts_on is not None and self.until < self.starts_on:
            msg = "until must not be before starts_on"
            raise ValueError(msg)
        return self
