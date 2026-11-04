"""Hall of Heroes: a members-only, raider.io-style leaderboard and per-member profile.

Attendance for raids/events/EP/attendance-rate is defined once, in ``sidequest_api.lib.attendance.attended_condition``
(a SQLAlchemy condition over ``EventSignup`` joined to ``GuildEvent``); every stat here is derived from it rather
than from a separate "attended" concept.

``SEASONS`` is the only thing to touch to add a season: append one more entry with a ``starts_at`` after the
previous season's ``ends_at`` (``None`` means "still running").
"""

from datetime import date, datetime  # pydantic needs them at runtime
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field

from sidequest_common.schemas.badges import EarnedBadge
from sidequest_common.schemas.events import EventKind, WowClass
from sidequest_common.schemas.stats import StatsHourCell


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

    ep: int = Field(description="Renown (EP) earned in this season.")
    raids_attended: int
    events_attended: int
    attendance_rate: float = Field(
        description="Attended divided by signed-up for completed events in range. 0.0 with no signed-up "
        "completed events."
    )


class HeroRow(BaseModel):
    """One leaderboard row."""

    rank: int | None = Field(description="Position by EP this season, None for members listed with no EP yet.")
    member_id: int
    discord_id: str
    display_name: str
    avatar_url: str | None
    wow_class: WowClass | None
    chat_level: int
    ep: int = Field(description="Renown (EP) earned this season.")
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
    ep: int = Field(description="Renown (EP) this event awarded the member.")


class HeroProfile(BaseModel):
    """``GET /api/heroes/{member_id}``."""

    member_id: int
    discord_id: str
    display_name: str
    avatar_url: str | None
    wow_class: WowClass | None
    rank: int | None = Field(
        description="Rank within the current season's leaderboard, None if outside it (no EP this season)."
    )
    chat_level: int
    chat_xp: int
    chat_xp_into_level: int
    chat_xp_for_next_level: int
    seasons: dict[str, HeroSeasonStats]
    all_time: HeroSeasonStats
    first_event_date: date | None
    recent_events: list[HeroRecentEvent]
    badges: list[EarnedBadge]


class HeroXPSources(BaseModel):
    """Breakdown of a member's lifetime XP by source. ``earlier`` is XP earned before per-source tracking started."""

    chat: int
    voice: int
    events: int
    groups: int
    earlier: int = Field(description="``max(0, xp - (chat + voice + events + groups))``.")


class HeroLevelReward(BaseModel):
    """A level-role reward, with the role's current name."""

    level: int
    role_name: str


class HeroDay(BaseModel):
    """Activity on one America/Chicago calendar day."""

    day: date
    messages: int
    voice_minutes: int


class HeroActivity(BaseModel):
    """``GET /api/heroes/{member_id}/activity``: MEE6-style stats for a member's Hall of Heroes profile."""

    member_id: int
    level: int
    xp: int
    xp_into_level: int
    xp_for_next_level: int
    xp_rank: int | None = Field(description="Rank among guild members by total XP, like `/rank`; `null` if unranked.")
    ranked_members: int
    next_reward: HeroLevelReward | None = Field(description="The lowest level-role reward above the current level.")
    message_count: int = Field(description="Lifetime message count.")
    voice_minutes: int = Field(description="All tracked voice minutes, lifetime.")
    events_attended: int
    groups_joined: int
    messages_30d: int
    voice_minutes_30d: int
    chat_rank_30d: int | None = Field(description="Rank among members by 30-day messages; `null` if they sent none.")
    voice_rank_30d: int | None = Field(
        description="Rank among members by 30-day voice minutes; `null` if they had none."
    )
    current_streak_days: int = Field(description="Consecutive America/Chicago days with a message or voice minute.")
    longest_streak_days: int
    xp_sources: HeroXPSources
    days: list[HeroDay] = Field(description="Last 30 days including today, oldest first, zero-filled.")
    heatmap: list[StatsHourCell] = Field(description="Last 90 days, non-zero weekday/hour cells only.")
    tracking_since: datetime | None
