"""Attendance: marking who came to an event, bot-reported voice time, and the GM attendance report.

See ``sidequest_api.lib.attendance`` for the SQL conditions ``attended``/no-show status feed into.
"""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field

from sidequest_common.schemas.events import EventKind, EventStatus, SignupRole, SignupStatus, WowClass


class AttendanceRange(StrEnum):
    """A reporting window for ``GET /api/attendance/report`` and ``/trends``."""

    LAST_30 = "last_30"
    SEASON = "season"
    ALL_TIME = "all_time"


class AttendanceEventSummary(BaseModel):
    """One past event, as listed on the attendance tab's event picker."""

    id: UUID
    title: str
    kind: EventKind
    starts_at: datetime
    status: EventStatus
    attendance_taken_at: datetime | None
    needs_attendance: bool
    """``True`` when the event has happened, isn't cancelled, and attendance hasn't been taken yet."""


class WalkInCandidate(BaseModel):
    """A guild member not currently signed up for the event, offered as a walk-in on the marking screen."""

    member_id: int
    display_name: str
    avatar_url: str | None


class AttendanceSignup(BaseModel):
    """One sign-up on the attendance marking screen, with the bot's reported voice time."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    signup_id: UUID
    member_id: int
    display_name: str
    avatar_url: str | None
    character: str | None
    wow_class: WowClass | None = Field(alias="class")
    role: SignupRole | None
    status: SignupStatus
    attended: bool | None
    is_walk_in: bool
    voice_minutes: int
    suggested_attended: bool
    """The Came/No-show checkbox's pre-tick before an officer touches it: the stored ``attended`` once attendance
    has been taken, else ``True`` for a ``signed`` sign-up or anyone with ``voice_minutes`` at or above the
    presence threshold, else ``False``."""


class AttendanceDetail(BaseModel):
    """``GET/PUT /api/events/{id}/attendance`` (officer): the marking screen for one event."""

    event: AttendanceEventSummary
    signups: list[AttendanceSignup]
    walk_in_candidates: list[WalkInCandidate]


class AttendanceMarkEntry(BaseModel):
    """One sign-up's Came/No-show decision."""

    signup_id: UUID
    attended: bool


class WalkInCreate(BaseModel):
    """A member who came without signing up. ``character``/``class``/``role`` are required for raid/dungeon events."""

    model_config = ConfigDict(populate_by_name=True)

    member_id: int
    character: str | None = Field(default=None, min_length=1, max_length=24)
    wow_class: WowClass | None = Field(default=None, alias="class")
    role: SignupRole | None = None


class AttendanceMark(BaseModel):
    """Body for ``PUT /api/events/{id}/attendance`` (officer). Sets ``attendance_taken_at`` to now.

    Sign-ups not listed in ``entries`` are left as-is (unmarked, unless a previous save already marked them):
    tentative/absent sign-ups default to not marked.
    """

    entries: list[AttendanceMarkEntry] = Field(default_factory=list)
    walk_ins: list[WalkInCreate] = Field(default_factory=list)


class VoicePresenceEntry(BaseModel):
    """One Discord member's cumulative voice minutes for an event, so far."""

    discord_id: str
    minutes: int = Field(ge=0)


class VoicePresenceReport(BaseModel):
    """Bot -> API: cumulative voice minutes per member for one event, so far.

    Idempotent: the API stores ``max(existing, reported)`` per ``discord_id`` listed (never an increment, and
    never lowers a stored total), so the bot can push repeatedly -- including after its own in-memory counter has
    reset on restart -- without double-counting or regressing a member's total.
    """

    event_id: UUID
    entries: list[VoicePresenceEntry] = Field(default_factory=list)


class MemberAttendanceRow(BaseModel):
    """One member's line on ``GET /api/attendance/report``."""

    member_id: int
    display_name: str
    avatar_url: str | None
    signed_up: int
    came: int
    no_shows: int
    walk_ins: int
    attendance_rate: float
    """Attended signed (non-walk-in) sign-ups / signed sign-ups, ``0.0`` if the member never signed up in range.

    ``came`` (which includes walk-ins) stays a separate display count above and never raises this above 1.0.
    """
    last_attended: datetime | None


class AttendanceReport(BaseModel):
    """``GET /api/attendance/report`` (GM)."""

    range: AttendanceRange
    raids_only: bool
    rows: list[MemberAttendanceRow]


class AttendanceTrendPoint(BaseModel):
    """One week's attendance on the trend chart."""

    week_start: date
    attendees: int
    """Distinct members who came that week."""
    signed_up: int
    show_rate: float
    """Attended signed (non-walk-in) sign-ups / signed sign-ups for events starting that week, ``0.0`` if nobody
    signed up. ``attendees`` (distinct members who came, which includes walk-ins) stays a separate display count
    above and never raises this above 1.0.
    """


class AttendanceTrends(BaseModel):
    """``GET /api/attendance/trends`` (GM): weekly attendance over the chosen range, oldest week first."""

    range: AttendanceRange
    raids_only: bool
    points: list[AttendanceTrendPoint]
