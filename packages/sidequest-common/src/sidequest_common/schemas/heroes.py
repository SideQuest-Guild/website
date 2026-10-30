"""Hall of Heroes: a members-only, raider.io-style leaderboard and per-member profile.

Attendance for raids/events/EP/attendance-rate is defined once, in ``sidequest_api.lib.attendance.attended_condition``
(a SQLAlchemy condition over ``EventSignup`` joined to ``GuildEvent``); every stat here is derived from it rather
than from a separate "attended" concept.

``SEASONS`` is the only thing to touch to add a season: append one more entry with a ``starts_at`` after the
previous season's ``ends_at`` (``None`` means "still running").
"""

from datetime import date, datetime  # pydantic needs them at runtime
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict

from sidequest_common.schemas.badges import EarnedBadge
from sidequest_common.schemas.events import EventKind, WowClass


class Season(BaseModel):
    """One competitive season. Open-ended (``ends_at: None``) until a later season starts."""

    id: str
    name: str
    starts_at: datetime
    ends_at: datetime | None


SEASONS: tuple[Season, ...] = (
    Season(
        id="season-one",
        name="Season One",
        starts_at=datetime.fromisoformat("2026-11-04T00:00:00+00:00"),
        ends_at=None,
    ),
)
"""Ordered oldest-first. The last entry's ``ends_at`` is always ``None`` (the current season)."""


class HeroSeasonStats(BaseModel):
    """One member's stats for one season (or all time)."""

    ep: int
    raids_attended: int
    events_attended: int
    attendance_rate: float
    """``attended / signed-up`` for completed events in range; ``0.0`` with no signed-up completed events."""


class HeroRow(BaseModel):
    """One leaderboard row."""

    rank: int
    member_id: int
    discord_id: str
    display_name: str
    avatar_url: str | None
    wow_class: WowClass | None
    chat_level: int
    ep: int
    raids_attended: int
    events_attended: int
    badge_ids: list[str]


class HeroLeaderboard(BaseModel):
    """``GET /api/heroes``."""

    season_id: str
    season_name: str
    rows: list[HeroRow]


class HeroRecentEvent(BaseModel):
    """One recent event a member attended, for the profile's recent-events list."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: EventKind
    title: str
    starts_at: datetime
    ep: int


class HeroProfile(BaseModel):
    """``GET /api/heroes/{member_id}``."""

    member_id: int
    discord_id: str
    display_name: str
    avatar_url: str | None
    wow_class: WowClass | None
    rank: int | None
    """Rank within the current season's leaderboard, ``None`` if outside it (no EP this season)."""
    chat_level: int
    chat_xp: int
    chat_xp_into_level: int
    chat_xp_for_next_level: int
    seasons: dict[str, HeroSeasonStats]
    all_time: HeroSeasonStats
    first_event_date: date | None
    recent_events: list[HeroRecentEvent]
    badges: list[EarnedBadge]
