"""Officer-facing server stats: ``GET /api/stats``.

Aggregated from ``member_activity_hour`` (chat/voice minutes and the XP they earned), ``XPGrant`` (event/group
XP), the codebase's shared attendance rule (``sidequest_api.lib.attendance.attended_condition``), and the same
counted-group rule used for group XP (``peak_size >= 2`` and ``grouped_minutes``/member ``minutes >=
COUNTED_GROUP_MINUTES``). Times, days, and weekday/hour buckets are America/Chicago.
"""

from datetime import date, datetime  # pydantic needs them at runtime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class StatsRange(StrEnum):
    """The window ``GET /api/stats`` reports over."""

    SEVEN_DAYS = "7d"
    THIRTY_DAYS = "30d"
    NINETY_DAYS = "90d"
    ALL = "all"


class StatsPerson(BaseModel):
    """Someone on a stats list. ``member_id`` is set when they have a site account (links to their profile)."""

    discord_id: str
    display_name: str
    avatar_url: str | None = None
    member_id: int | None = None


class StatsLeader(BaseModel):
    """One line on a top-10 leaderboard; what ``value`` counts depends on which list it's on."""

    person: StatsPerson
    value: int


class StatsTotals(BaseModel):
    """Guild-wide activity totals over a window."""

    active_members: int = Field(description="Distinct members with any message, voice minute, or attended event.")
    messages: int
    voice_minutes: int
    events_attended: int
    groups_joined: int = Field(description="Counted #lfg group joins (peak size 2+, 10+ minutes), like group XP.")
    xp_gained: int = Field(description="Chat and voice XP earned, plus event/group XP paid out, in the window.")


class StatsTrendPoint(BaseModel):
    """One point on the activity trend chart: a day or a Monday-start week, per ``GuildStats.trend_bucket``."""

    start: date
    messages: int
    voice_minutes: int
    active_members: int


class StatsHourCell(BaseModel):
    """Activity in one weekday/hour slot, America/Chicago. ``weekday`` 0 is Monday."""

    weekday: int = Field(ge=0, le=6)
    hour: int = Field(ge=0, le=23)
    messages: int
    voice_minutes: int


class StatsQuietMember(BaseModel):
    """A roster member still in the guild with no activity in the last 30 days."""

    person: StatsPerson
    last_active_at: datetime | None = Field(description="Most recent message, voice minute, or attended event ever.")
    level: int


class GuildStats(BaseModel):
    """``GET /api/stats?range=`` (officer): totals, trend, heatmap, leaderboards, and quiet members."""

    range: StatsRange
    since: datetime | None = Field(description="Start of the window; `null` for `all`.")
    tracking_since: datetime | None = Field(description="Earliest hour the bot has ever recorded activity for.")
    totals: StatsTotals
    previous: StatsTotals | None = Field(
        description="The same-length window right before `since`, for a trend comparison; `null` for `all`."
    )
    trend_bucket: Literal["day", "week"] = Field(description="`day` for 7d/30d, Monday-start `week` for 90d/all.")
    trend: list[StatsTrendPoint] = Field(
        description="Oldest first, zero-filled across the window (`all`: from `tracking_since`)."
    )
    heatmap: list[StatsHourCell] = Field(description="Non-zero weekday/hour cells only.")
    top_chatters: list[StatsLeader] = Field(description="Highest message count, max 10.")
    top_voice: list[StatsLeader] = Field(description="Most voice minutes, max 10.")
    top_events: list[StatsLeader] = Field(description="Most attended events, max 10.")
    top_groups: list[StatsLeader] = Field(description="Most counted #lfg groups joined, max 10.")
    top_xp: list[StatsLeader] = Field(description="Most XP gained in the window, max 10.")
    gone_quiet: list[StatsQuietMember] = Field(
        description=(
            "Roster members still in the guild with no messages, voice, or attended event in the last 30 days "
            "(independent of `range`). Never-active first, then oldest last-active, max 25."
        )
    )
