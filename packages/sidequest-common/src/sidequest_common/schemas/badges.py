"""Hall of Heroes badge definitions and earned-badge schemas.

Badges are defined in code, not configured on the site: ``BADGES`` is the single source of truth for every badge's
id, display name, description, icon, and the color its Discord role gets. The bot creates one Discord role per
badge (stored in ``GuildConfigSchema.badge_role_ids``) and keeps membership in sync with ``MemberBadge`` rows the
API computes. Adjust thresholds here; nothing else needs to change.
"""

from datetime import datetime  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict


class BadgeDefinition(BaseModel):
    """One badge's fixed metadata. ``color`` is a Discord role color (0xRRGGBB)."""

    id: str
    name: str
    description: str
    icon: str
    color: int


BADGE_LIST: tuple[BadgeDefinition, ...] = (
    BadgeDefinition(
        id="first_steps",
        name="First Steps",
        description="Attended their first guild event.",
        icon="👣",
        color=0x9AA6B2,
    ),
    BadgeDefinition(
        id="first_raid",
        name="First Raid",
        description="Attended their first raid.",
        icon="⚔️",
        color=0xC69B6D,
    ),
    BadgeDefinition(
        id="raid_regular",
        name="Raid Regular",
        description="Attended 10 raids with the guild.",
        icon="🛡️",
        color=0x4A9DF2,
    ),
    BadgeDefinition(
        id="raid_veteran",
        name="Raid Veteran",
        description="Attended 25 raids with the guild.",
        icon="🏅",
        color=0xB673F5,
    ),
    BadgeDefinition(
        id="perfect_month",
        name="Perfect Month",
        description="Attended every raid the guild ran in a calendar month (at least 4 raids that month).",
        icon="🌙",
        color=0xFFD36A,
    ),
    BadgeDefinition(
        id="founding_member",
        name="Founding Member",
        description="Confirmed on the guild roster before launch.",
        icon="🏰",
        color=0xF48CBA,
    ),
    BadgeDefinition(
        id="chatterbox",
        name="Chatterbox",
        description="Reached chat level 10.",
        icon="💬",
        color=0x3FC7EB,
    ),
    BadgeDefinition(
        id="top_helper",
        name="Top Helper",
        description="Attended the most dungeon and leveling events last month. A moving monthly title.",
        icon="🌟",
        color=0xFF8C2A,
    ),
)

BADGES: dict[str, BadgeDefinition] = {badge.id: badge for badge in BADGE_LIST}

RAID_REGULAR_THRESHOLD = 10
RAID_VETERAN_THRESHOLD = 25
PERFECT_MONTH_MIN_RAIDS = 4
CHATTERBOX_LEVEL = 10
FOUNDING_MEMBER_CUTOFF_ISO = "2026-11-04T00:00:00+00:00"
"""Members confirmed on the roster before this instant (the launch date, UTC midnight) earn Founding Member."""


class EarnedBadge(BaseModel):
    """One badge a member has earned, for the profile's badge case."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    icon: str
    earned_at: datetime


class BadgeRoleState(BaseModel):
    """One member's current badge ids, for the bot's role sync (``GET /api/guilds/{id}/badges/state``)."""

    discord_id: int
    badge_ids: list[str]


class PendingBadgeAnnouncement(BaseModel):
    """A newly earned badge not yet announced in Discord."""

    discord_id: int
    badge_id: str
    name: str
    description: str


class BadgeSyncReport(BaseModel):
    """``GET /api/guilds/{id}/badges/sync``: recomputes every member's badges, then reports the result.

    ``role_state`` is every linked member's full current badge set (the bot diffs this against actual role
    membership). ``pending`` is newly earned badges not yet announced; the bot posts them, then calls
    ``POST /api/guilds/{id}/badges/ack`` to mark them announced.
    """

    role_state: list[BadgeRoleState]
    pending: list[PendingBadgeAnnouncement]


class BadgeAck(BaseModel):
    """Body for ``POST /api/guilds/{id}/badges/ack``: badges whose announcement has posted."""

    discord_id: int
    badge_id: str
