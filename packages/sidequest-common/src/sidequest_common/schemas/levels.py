"""Leveling schemas, and how much XP each kind of activity is worth."""

from datetime import datetime  # pydantic needs it at runtime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

VOICE_XP_PER_MINUTE = 5
"""XP per minute in voice with at least one other member, undeafened, outside the AFK channel."""
EVENT_XP = 150
"""XP for attending a guild event: once attendance marks you came, or a day after it started if nobody took it."""
GROUP_XP = 50
"""XP for each #lfg group you spent ``COUNTED_GROUP_MINUTES`` in, once the group has ended."""
EVENT_XP_GRACE_HOURS = 24
"""An event nobody took attendance for pays its sign-ups this long after it started."""
XP_LOOKBACK_DAYS = 30
"""Events and groups older than this never pay XP, so turning leveling on doesn't reward ancient history."""
MAX_VOICE_XP_MEMBERS = 500
MAX_BACKFILL_BUCKETS = 5000
"""Buckets accepted per ``PUT /activity/messages`` call."""


class XPSource(StrEnum):
    """What earned XP besides chat."""

    VOICE = "voice"
    EVENT = "event"
    GROUP = "group"


class XPAwardResult(BaseModel):
    """Outcome of ``POST /members/{user_id}/xp`` (one chat message's worth of XP).

    ``awarded`` is False while the member is on cooldown (or leveling is disabled); every other field then
    reflects the unchanged totals. ``earned_role_ids`` are level-role rewards for every level crossed by this
    award; ``remove_role_ids`` are lower level-roles to take away when the guild has ``level_roles_stack=False``.
    """

    awarded: bool
    amount: int = Field(description="XP (experience points) awarded by this message.")
    xp: int = Field(description="The member's new total XP (experience points).")
    level: int
    previous_level: int
    leveled_up: bool
    earned_role_ids: list[int] = Field(default_factory=list)
    remove_role_ids: list[int] = Field(default_factory=list)


class XPGrantResult(XPAwardResult):
    """XP one member got from voice, an event or an #lfg group, with the same level-up details as a chat award."""

    user_id: int = Field(description="The member's Discord user ID.")
    source: XPSource


class VoiceXPRequest(BaseModel):
    """Body for ``POST /xp/voice``: members who spent ``minutes`` in voice, already filtered by the bot."""

    user_ids: list[int] = Field(
        default_factory=list, max_length=MAX_VOICE_XP_MEMBERS, description="Discord user IDs to award XP to."
    )
    present_user_ids: list[int] = Field(
        default_factory=list,
        max_length=MAX_VOICE_XP_MEMBERS,
        description=(
            "Discord user IDs present under the stats voice rule (any voice/stage channel but the AFK channel, "
            "with at least two non-bot members), which may be a superset of user_ids. Their voice minutes are "
            "recorded even when leveling is disabled or they aren't eligible for voice XP."
        ),
    )
    minutes: int = Field(default=1, ge=1, le=10, description="Minutes each member spent in voice since the last call.")


class MessageBackfillBucket(BaseModel):
    """One hour's message count for one member, read once from Discord channel history."""

    user_id: int = Field(description="The member's Discord user ID.")
    hour_start: datetime = Field(description="The UTC hour this count covers; normalized to the hour on save.")
    messages: int = Field(ge=0, description="Messages sent in that hour.")


class MessageBackfill(BaseModel):
    """Body for ``PUT /activity/messages``: message counts read once from Discord channel history."""

    buckets: list[MessageBackfillBucket] = Field(max_length=MAX_BACKFILL_BUCKETS)


class MessageBackfillResult(BaseModel):
    """Reply to ``PUT /activity/messages``."""

    buckets: int = Field(description="How many (member, hour) buckets were touched.")


class XPActivityReport(BaseModel):
    """Event and #lfg group XP paid out by one ``POST /xp/activity`` call; empty when nothing new qualified."""

    grants: list[XPGrantResult] = Field(default_factory=list)


class RankSchema(BaseModel):
    """A member's standing. ``rank`` is 1-based position by XP, or None if they have no XP yet."""

    user_id: int
    rank: int | None
    xp: int = Field(description="The member's total XP (experience points).")
    level: int
    message_count: int
    xp_into_level: int = Field(description="XP (experience points) earned since reaching the current level.")
    xp_for_next_level: int = Field(description="XP (experience points) needed to reach the next level.")


class LeaderboardEntry(BaseModel):
    """One leaderboard row."""

    rank: int
    user_id: int
    xp: int = Field(description="The member's total XP (experience points).")
    level: int
    message_count: int


class LeaderboardPage(BaseModel):
    """A page of the leaderboard, highest XP first."""

    entries: list[LeaderboardEntry]
    total: int
    limit: int
    offset: int


MAX_XP = 10_000_000_000
"""Ceiling for admin XP overrides (~level 1800); keeps the level calculation bounded and fits a BIGINT."""


class SetXPRequest(BaseModel):
    """Admin override of a member's XP total (level is recomputed)."""

    xp: int = Field(ge=0, le=MAX_XP, description="The new total XP (experience points) to set.")


class MemberLevelSchema(BaseModel):
    """Raw stored level row."""

    model_config = ConfigDict(from_attributes=True)

    guild_id: int
    user_id: int
    xp: int = Field(description="The member's total XP (experience points).")
    level: int
    message_count: int


class LevelRoleSchema(BaseModel):
    """Role rewarded at a level."""

    model_config = ConfigDict(from_attributes=True)

    level: int
    role_id: int


class LevelRoleUpsert(BaseModel):
    """Body for ``PUT /level-roles/{level}``."""

    role_id: int
