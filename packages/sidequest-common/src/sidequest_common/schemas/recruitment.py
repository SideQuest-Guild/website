"""Recruitment drive schemas: constants, enums, the addon export/import additions, and the site HTTP API.

``local://recruitment-contract.md`` is the source of truth. A drive is a ``GuildEvent`` of kind ``recruitment``
(``sidequest_common.schemas.events.EventKind.RECRUITMENT``) running 14 days by default; inviters earn
``RECRUIT_REWARD_COPPER`` per recruit who stays ``RECRUIT_STAY_DAYS`` days and reaches ``RECRUIT_MIN_LEVEL``, paid
out ``DRIVE_SETTLE_DAYS`` after the drive ends. Who invited whom comes from the in-game guild log
(``ExportGuildLogEntry``), not the addon.
"""

from datetime import datetime, timedelta  # pydantic needs datetime at runtime
from enum import StrEnum
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, Field

RECRUIT_REWARD_COPPER = 10_000
"""1g, paid to the inviter per qualifying recruit."""
RECRUIT_MIN_LEVEL = 10
RECRUIT_STAY_DAYS = 7
DRIVE_SETTLE_DAYS = 7
"""Payouts settle this many days after the drive's ``ends_at``."""
DRIVE_DEFAULT_DAYS = 14
"""The site form's default drive length."""
RECRUIT_JOIN_WINDOW = timedelta(hours=48)
"""A join must follow its invite within this window, else the recruit is ``never_joined``."""

MAX_GUILD_LOG_ENTRIES = 500
MAX_RECRUIT_PAYOUTS_PAID = 200
MAX_RECRUITMENT_LEADERS = 15
"""Cap on ``RecruitmentTally.leaders``, the most relevant inviters for the forum starter post."""
GUILD_LOG_DEDUPE_WINDOW = timedelta(hours=2)
"""A re-uploaded guild log row with the same kind/actor/target within this window of a stored row is the same entry."""
RECRUIT_NAME_MAX_LENGTH = 64
"""Matches the addon's character name format (``roster.members[].character``)."""


class GuildLogKind(StrEnum):
    """One kind of in-game guild event log entry (``QueryGuildEventLog``/``GetGuildEventInfo``)."""

    INVITE = "invite"
    JOIN = "join"
    QUIT = "quit"
    REMOVE = "remove"


class DriveRecruitStatus(StrEnum):
    """Where one recruit is in a drive's 7-day qualification clock."""

    INVITED = "invited"
    COUNTING = "counting"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"


class DriveRecruitReason(StrEnum):
    """Why a recruit is ``disqualified``. Only set alongside ``DriveRecruitStatus.DISQUALIFIED``."""

    RETURNING = "returning"
    OWN_ALT = "own_alt"
    LEFT = "left"
    LOW_LEVEL = "low_level"
    NEVER_JOINED = "never_joined"


class PaidVia(StrEnum):
    """How a recruit's payout was marked paid: the site's "Mark paid" button, or the addon's mail-send button."""

    SITE = "site"
    ADDON = "addon"


# --- Addon -> site: SQX1 export additions (additive; ``v`` stays 2) ------------------------------------------


class ExportGuildLogEntry(BaseModel):
    """One ``SQX1:`` guild event log row (max ``MAX_GUILD_LOG_ENTRIES``). ``at`` is rounded down to the hour.

    ``actor`` is the inviter for ``invite``, the member for ``join``/``quit``, or the removing officer for
    ``remove``; ``target`` is the invitee for ``invite`` or the removed member for ``remove``, and omitted for
    ``join``/``quit``. ``promote``/``demote`` entries are never exported.
    """

    kind: GuildLogKind
    actor: str = Field(max_length=RECRUIT_NAME_MAX_LENGTH)
    target: str | None = Field(default=None, max_length=RECRUIT_NAME_MAX_LENGTH)
    at: int


class ExportRecruitPayoutPaid(BaseModel):
    """One ``SQX1:`` row for a payout the addon's mail button already sent (max ``MAX_RECRUIT_PAYOUTS_PAID``)."""

    event_id: UUID
    inviter: str = Field(max_length=RECRUIT_NAME_MAX_LENGTH)
    copper: int = Field(ge=0)
    at: int
    officer: str = Field(max_length=RECRUIT_NAME_MAX_LENGTH)


class GuildLogImportCounts(BaseModel):
    """Counts for the ``guild_log`` section of one import. ``merged`` matches a stored row within the dedupe window."""

    new: int = 0
    merged: int = 0


class RecruitPayoutImportCounts(BaseModel):
    """Counts for the ``recruit_payouts_paid`` section of one import. ``already_paid`` is the idempotent no-op case."""

    new: int = 0
    already_paid: int = 0


# --- Site -> addon: SQI1 import addition (additive) -----------------------------------------------------------


class GameImportRecruitPayout(BaseModel):
    """One ``SQI1:`` officer payout row: one inviter's qualified, unpaid recruits for one settled drive."""

    event_id: UUID
    title: str
    inviter: str
    copper: int
    recruits: list[str]
    settles_at: int


# --- Site HTTP API (tag "Recruitment drives") -------------------------------------------------------------------


class RecruitmentDriveTotals(BaseModel):
    """Headcounts across a drive's recruits, by ``DriveRecruitStatus`` plus how many are paid."""

    invited: int
    joined: int
    counting: int
    qualified: int
    disqualified: int
    paid: int


class RecruitLeader(BaseModel):
    """One inviter's standing in a drive's leaderboard."""

    inviter: str
    member_name: str | None
    discord_id: str | None = Field(description="The inviter's Discord id as a string (too big for JS numbers).")
    invited: int
    joined: int
    counting: int
    qualified: int


class DriveRecruit(BaseModel):
    """One recruit's row in a drive's detail, including their qualification clock and pay state."""

    recruit: str
    inviter: str
    invited_at: datetime
    joined_at: datetime | None
    qualifies_at: datetime | None
    status: DriveRecruitStatus
    reason: DriveRecruitReason | None
    paid_at: datetime | None


class RecruitmentDrive(BaseModel):
    """``GET /api/events/{event_id}/recruitment``: one drive's full detail, leaderboard, and recruit rows."""

    event_id: UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    settles_at: datetime
    reward_copper: int
    min_level: int
    stay_days: int
    totals: RecruitmentDriveTotals
    leaders: list[RecruitLeader]
    recruits: list[DriveRecruit]


class RecruitPayout(BaseModel):
    """``GET /api/recruitment/payouts``: one inviter's owed (or already-paid) total for one settled drive."""

    event_id: UUID
    title: str
    settles_at: datetime
    inviter: str
    member_name: str | None
    recruits: list[str]
    copper: int
    paid_at: datetime | None
    paid_by: str | None
    paid_via: PaidVia | None


class RecruitPayoutMarkPaid(BaseModel):
    """Body for ``POST /api/recruitment/payouts/paid`` (officer). Idempotent."""

    event_id: UUID
    inviter: str


# --- Site -> bot (event sync; additive with defaults) -----------------------------------------------------------


class RecruitmentTally(BaseModel):
    """``DiscordEventPush.recruitment``: a drive's live leaderboard, for the forum starter post."""

    reward_copper: int
    settles_at: datetime
    invited: int
    joined: int
    qualified: int
    leaders: list[RecruitLeader] = Field(default_factory=list, max_length=MAX_RECRUITMENT_LEADERS)


class RecruitShoutout(BaseModel):
    """One qualified recruit's shout-out, queued to post as a comment on the drive's forum thread."""

    id: UUID
    thread_id: int
    event_id: UUID
    inviter: str
    inviter_discord_id: int | None
    recruit: str
    reward_copper: int


class RecruitShoutoutAck(BaseModel):
    """``POST /api/guilds/{guild_id}/event-sync/recruit-shoutouts/ack``: the bot posted these shout-outs."""

    ids: list[UUID]
