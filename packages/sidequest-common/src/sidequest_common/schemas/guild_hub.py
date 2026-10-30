"""Guild hub v2 schemas: the addon export/import v2 sections and the ``/api/guild/*`` HTTP API.

``local://addon-contract-v2.md`` is the source of truth; field names and string prefixes here are binding. Lua json
encoders drop nil keys rather than emitting null (see ``sidequest_common.schemas.epgp``), so every nullable
contract field here is a pydantic default, not a required key.
"""

from datetime import datetime  # pydantic needs it at runtime
from enum import StrEnum
from typing import Annotated
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from sidequest_common.schemas.events import SignupRole, SignupStatus, WowClass


def _lower_class(value: object) -> object:
    return value.lower() if isinstance(value, str) else value


GameClass = Annotated[WowClass, BeforeValidator(_lower_class)]
"""A class as the addon sends it: the game's uppercase token (``WARRIOR``), stored as the site's lowercase value."""

MAX_ROSTER_MEMBERS = 1000
MAX_PROFESSION_PAIRS = 400
MAX_RECIPES_PER_PROFESSION = 2000
MAX_SIGNUPS_V2 = 500
MAX_BANK_ENTRIES = 2000
MAX_ANNOUNCEMENTS_V2 = 200
MAX_RECRUITS_V2 = 200
MAX_MEMBER_NOTES_V2 = 500

ANNOUNCEMENT_TEXT_MAX = 500
NOTE_TEXT_MAX = 500
RECRUIT_NOTE_MAX = 500


class RecruitStatus(StrEnum):
    """A recruiting candidate's status in the vetting pipeline."""

    APPLICANT = "applicant"
    TRIAL = "trial"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class RecruitVoteChoice(StrEnum):
    """An officer's vote on a recruit."""

    YES = "yes"
    NO = "no"
    WAIT = "wait"


class BankKind(StrEnum):
    """What kind of guild bank activity log row this is."""

    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    MOVE = "move"
    REPAIR = "repair"
    BUY_TAB = "buy_tab"
    DEPOSIT_MONEY = "deposit_money"
    WITHDRAW_MONEY = "withdraw_money"


class AnnouncementSource(StrEnum):
    """Where an announcement was made."""

    GAME = "game"
    SITE = "site"


class NewsKind(StrEnum):
    """What kind of guild news feed item this is."""

    BOSS_KILL = "boss_kill"
    FIRST_KILL = "first_kill"
    LOOT = "loot"
    LEVEL = "level"
    JOINED = "joined"
    ANNOUNCEMENT = "announcement"
    BADGE = "badge"


LEVEL_MILESTONE_STEP = 10
LEFT_GUILD_AFTER_DAYS = 30
INACTIVE_AFTER_DAYS = 14


# --- Addon export v2 (``SQX1:``, ``"v": 2``): new optional top-level arrays ------------------------------------


class ExportRosterMember(BaseModel):
    """One roster row in the export payload's ``roster.members``."""

    model_config = ConfigDict(populate_by_name=True)

    character: str = Field(max_length=64)
    rank: str = Field(max_length=60)
    rank_index: int = 0
    level: int = 0
    wow_class: GameClass | None = Field(default=None, alias="class")
    zone: str = Field(default="", max_length=120)
    online: bool = False
    last_online_hours: float = 0


class ExportRoster(BaseModel):
    """The ``roster`` object in the export payload: one sweep, taken at ``taken_at``."""

    taken_at: int
    members: list[ExportRosterMember] = Field(default_factory=list, max_length=MAX_ROSTER_MEMBERS)


class ExportRecipe(BaseModel):
    """One known recipe in a profession scan."""

    id: int
    name: str = Field(max_length=120)
    item_id: int | None = None


class ExportProfession(BaseModel):
    """One character's profession scan in the export payload."""

    character: str = Field(max_length=64)
    profession: str = Field(max_length=40)
    skill: int = 0
    max_skill: int = 0
    scanned_at: int
    recipes: list[ExportRecipe] = Field(default_factory=list, max_length=MAX_RECIPES_PER_PROFESSION)


class ExportSignupV2(BaseModel):
    """One in-game sign-up relayed by an officer's addon."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(max_length=120)
    event_id: UUID
    character: str = Field(max_length=64)
    status: SignupStatus
    role: SignupRole | None = None
    wow_class: GameClass | None = Field(default=None, alias="class")
    comment: str | None = Field(default=None, max_length=200)
    at: int


class ExportBankEntry(BaseModel):
    """One guild bank log row."""

    id: str = Field(max_length=120)
    at: int
    character: str | None = Field(default=None, max_length=64)
    kind: BankKind
    item_id: int | None = None
    item_name: str | None = Field(default=None, max_length=120)
    count: int = 0
    money: int = 0
    tab: int | None = None


class ExportAnnouncement(BaseModel):
    """One announcement posted in game."""

    id: str = Field(max_length=120)
    text: str = Field(max_length=ANNOUNCEMENT_TEXT_MAX)
    officer: str = Field(max_length=64)
    at: int
    discord: bool = False


class RecruitChecklist(BaseModel):
    """An officer's vetting checklist for one recruit."""

    talked: bool = False
    gear_check: bool = False
    first_raid: bool = False
    vouched: bool = False


class ExportRecruitVote(BaseModel):
    """One officer's vote on a recruit, within the export payload."""

    officer: str = Field(max_length=64)
    vote: RecruitVoteChoice
    at: int


class ExportRecruit(BaseModel):
    """One recruiting candidate in the export payload."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(max_length=120)
    character: str = Field(max_length=64)
    wow_class: GameClass | None = Field(default=None, alias="class")
    status: RecruitStatus
    note: str | None = Field(default=None, max_length=RECRUIT_NOTE_MAX)
    checklist: RecruitChecklist = Field(default_factory=RecruitChecklist)
    votes: list[ExportRecruitVote] = Field(default_factory=list)
    at: int


class ExportMemberNote(BaseModel):
    """One officer note about a character."""

    id: str = Field(max_length=120)
    character: str = Field(max_length=64)
    note: str = Field(max_length=NOTE_TEXT_MAX)
    officer: str = Field(max_length=64)
    at: int
    voided: bool = False


# --- Import counts (added to ``EpgpImportResult``) --------------------------------------------------------------


class RosterImportCounts(BaseModel):
    """Count of roster rows upserted by one import."""

    updated: int = 0


class ProfessionImportCounts(BaseModel):
    """Count of profession rows upserted by one import."""

    updated: int = 0


class SignupImportCounts(BaseModel):
    """Counts for the ``signups`` section of one import."""

    applied: int = 0
    skipped_older: int = 0
    unlinked: int = 0


class BankImportCounts(BaseModel):
    """Count of new bank log rows inserted by one import."""

    new: int = 0


class AnnouncementImportCounts(BaseModel):
    """Count of new announcement rows inserted by one import."""

    new: int = 0


class RecruitImportCounts(BaseModel):
    """Counts for the ``recruits`` section of one import."""

    new: int = 0
    updated: int = 0


class MemberNoteImportCounts(BaseModel):
    """Counts for the ``member_notes`` section of one import."""

    new: int = 0
    updated: int = 0
    voided: int = 0


# --- Site import v2 (``SQI1:``, additions): public, on-demand, and officer-only parts ----------------------------


class GameImportCharacter(BaseModel):
    """One of a member's characters in the ``members`` game-import section."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    name: str
    wow_class: WowClass | None = Field(default=None, alias="class")
    level: int
    is_main: bool


class GameImportBadgeRef(BaseModel):
    """One earned badge's id and display name."""

    id: str
    name: str


class GameImportMember(BaseModel):
    """One ``members`` row in the game-import payload's public part."""

    member_id: int
    name: str
    main: str | None
    wow_class: WowClass | None = Field(default=None, alias="class", serialization_alias="class")
    rank: str | None
    raid_status: str | None
    guild_ep: int
    attendance_rate: float
    events_attended: int
    badges: list[GameImportBadgeRef]
    characters: list[GameImportCharacter]

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class GameImportNews(BaseModel):
    """One ``news`` row in the game-import payload's public part."""

    id: str
    at: int
    kind: NewsKind
    text: str
    character: str | None
    item_id: int | None
    quality: int | None


class GameImportLedgerEntry(BaseModel):
    """One ledger row in a member's on-demand sheet."""

    at: int
    kind: str
    amount: int
    decayed: float
    reason: str
    note: str | None


class GameImportLootEntry(BaseModel):
    """One loot row in a member's on-demand sheet."""

    at: int
    item_id: int
    item_name: str
    quality: int
    gp: int
    response: str


class GameImportSheet(BaseModel):
    """One member's on-demand sheet: last 15 ledger entries and last 10 loot wins."""

    ledger: list[GameImportLedgerEntry]
    loot: list[GameImportLootEntry]


class GameImportCrafter(BaseModel):
    """One character's profession, recipes as ids (named in the shared ``recipe_names`` table)."""

    character: str
    member_id: int | None
    profession: str
    skill: int
    recipes: list[int]


class GameImportOfficerRecruit(BaseModel):
    """One recruit in the officer-only game-import part: same shape as the export, plus ``member_id``."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    id: str
    character: str
    wow_class: WowClass | None = Field(default=None, alias="class", serialization_alias="class")
    status: RecruitStatus
    note: str | None
    checklist: RecruitChecklist
    votes: list[ExportRecruitVote]
    at: int
    member_id: int | None


class GameImportOfficerNote(BaseModel):
    """One note in the officer-only game-import part: same shape as the export."""

    id: str
    character: str
    note: str
    officer: str
    at: int
    voided: bool


class GameImportInactiveMember(BaseModel):
    """One inactive member flagged in the officer-only game-import part."""

    member_id: int
    name: str
    last_seen_at: int | None
    last_raid_at: int | None


class GameImportOfficerPart(BaseModel):
    """The officer-only part of the game-import payload, never broadcast to the whole guild."""

    recruits: list[GameImportOfficerRecruit]
    member_notes: list[GameImportOfficerNote]
    inactive: list[GameImportInactiveMember]


# --- ``/api/guild/*`` HTTP API schemas ---------------------------------------------------------------------------


class GuildRosterCharacter(BaseModel):
    """One of a member's characters on ``GET /api/guild/roster``."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    name: str
    wow_class: WowClass | None = Field(default=None, alias="class", serialization_alias="class")
    level: int
    zone: str
    last_seen_at: datetime
    is_main: bool


class GuildRosterMember(BaseModel):
    """One member's row on ``GET /api/guild/roster``, alts grouped under their main."""

    member_id: int
    name: str
    rank: str | None
    raid_status: str | None
    main: str | None
    characters: list[GuildRosterCharacter]


class GuildRosterUnlinked(BaseModel):
    """One roster-only character with no linked member, on ``GET /api/guild/roster``."""

    name: str
    wow_class: WowClass | None = Field(default=None, alias="class", serialization_alias="class")
    level: int
    rank: str
    last_seen_at: datetime

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class GuildRoster(BaseModel):
    """Response for ``GET /api/guild/roster`` (member)."""

    taken_at: datetime | None
    members: list[GuildRosterMember]
    unlinked: list[GuildRosterUnlinked]


class GuildCrafterRow(BaseModel):
    """One character that knows a matched recipe, in ``GET /api/guild/crafters``."""

    character: str
    member_id: int | None
    member_name: str | None
    profession: str
    skill: int


class GuildCrafterResult(BaseModel):
    """One matched recipe and the characters that know it."""

    recipe_id: int
    recipe_name: str
    item_id: int | None
    crafters: list[GuildCrafterRow]


class GuildCrafterProfessionCount(BaseModel):
    """How many characters know each profession, for the ``professions`` filter list."""

    profession: str
    crafters: int


class GuildCrafters(BaseModel):
    """Response for ``GET /api/guild/crafters`` (member)."""

    results: list[GuildCrafterResult]
    professions: list[GuildCrafterProfessionCount]


class GuildNewsItem(BaseModel):
    """One row of ``GET /api/guild/news`` (public)."""

    id: UUID
    at: datetime
    kind: NewsKind
    text: str
    character: str | None
    item_id: int | None
    quality: int | None


class GuildNewsPage(BaseModel):
    """Response for ``GET /api/guild/news`` (public), newest first."""

    items: list[GuildNewsItem]


class GuildBankRow(BaseModel):
    """One row of ``GET /api/guild/bank`` (member)."""

    id: UUID
    at: datetime
    character: str | None
    member_name: str | None
    kind: BankKind
    item_id: int | None
    item_name: str | None
    count: int
    money: int
    tab: int | None


class GuildBankTotals(BaseModel):
    """Deposit/withdrawal totals over the last 30 days, for ``GET /api/guild/bank``."""

    deposits_30d: int
    withdrawals_30d: int


class GuildBankPage(BaseModel):
    """Response for ``GET /api/guild/bank`` (member), newest first."""

    rows: list[GuildBankRow]
    totals: GuildBankTotals


class GuildAnnouncementRow(BaseModel):
    """One row of ``GET /api/guild/announcements`` (public)."""

    id: UUID
    text: str
    author: str
    at: datetime
    source: AnnouncementSource
    posted_at: datetime | None


class GuildAnnouncementsPage(BaseModel):
    """Response for ``GET /api/guild/announcements`` (public), newest first, last 20."""

    items: list[GuildAnnouncementRow]


class GuildAnnouncementCreate(BaseModel):
    """Body for ``POST /api/guild/announcements`` (officer)."""

    text: str = Field(min_length=1, max_length=ANNOUNCEMENT_TEXT_MAX)
    discord: bool = False


# --- Officer recruiting + notes HTTP API schemas -------------------------------------------------------------


class EpgpRecruitRow(BaseModel):
    """One recruit, as returned by ``GET /api/epgp/recruits`` / mutated by ``PUT .../{id}``."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    id: UUID
    character: str
    wow_class: WowClass | None = Field(default=None, alias="class", serialization_alias="class")
    status: RecruitStatus
    note: str | None
    checklist: RecruitChecklist
    votes: list[ExportRecruitVote]
    member_id: int | None
    at: datetime


class EpgpRecruitList(BaseModel):
    """Response for ``GET /api/epgp/recruits`` (officer)."""

    recruits: list[EpgpRecruitRow]


class EpgpRecruitUpdate(BaseModel):
    """Body for ``PUT /api/epgp/recruits/{id}`` (officer). Only fields present change."""

    status: RecruitStatus | None = None
    note: str | None = Field(default=None, max_length=RECRUIT_NOTE_MAX)
    checklist: RecruitChecklist | None = None


class EpgpRecruitVoteCreate(BaseModel):
    """Body for ``POST /api/epgp/recruits/{id}/votes`` (officer)."""

    vote: RecruitVoteChoice


class EpgpMemberNoteRow(BaseModel):
    """One row of ``GET /api/epgp/member-notes`` (officer)."""

    id: UUID
    character: str
    member_id: int | None
    note: str
    officer: str
    at: datetime
    voided: bool


class EpgpMemberNoteList(BaseModel):
    """Response for ``GET /api/epgp/member-notes`` (officer)."""

    notes: list[EpgpMemberNoteRow]


# --- Bot: pending announcements ----------------------------------------------------------------------------------


class PendingAnnouncement(BaseModel):
    """One queued Discord announcement, for ``GET /api/guilds/{guild_id}/announcements/pending`` (bot)."""

    id: UUID
    text: str
    author: str
    at: datetime


class PendingAnnouncementsPage(BaseModel):
    """Response for ``GET /api/guilds/{guild_id}/announcements/pending`` (bot)."""

    items: list[PendingAnnouncement]


class AnnouncementPosted(BaseModel):
    """Body for ``POST /api/guilds/{guild_id}/announcements/{id}/posted`` (bot)."""

    message_id: int


class AnnouncementPostedResult(BaseModel):
    """Response for ``POST /api/guilds/{guild_id}/announcements/{id}/posted`` (bot)."""

    message_id: int


__all__ = (
    "ANNOUNCEMENT_TEXT_MAX",
    "INACTIVE_AFTER_DAYS",
    "LEFT_GUILD_AFTER_DAYS",
    "LEVEL_MILESTONE_STEP",
    "MAX_ANNOUNCEMENTS_V2",
    "MAX_BANK_ENTRIES",
    "MAX_MEMBER_NOTES_V2",
    "MAX_PROFESSION_PAIRS",
    "MAX_RECIPES_PER_PROFESSION",
    "MAX_RECRUITS_V2",
    "MAX_ROSTER_MEMBERS",
    "MAX_SIGNUPS_V2",
    "NOTE_TEXT_MAX",
    "RECRUIT_NOTE_MAX",
    "AnnouncementImportCounts",
    "AnnouncementPosted",
    "AnnouncementPostedResult",
    "AnnouncementSource",
    "BankImportCounts",
    "BankKind",
    "EpgpMemberNoteList",
    "EpgpMemberNoteRow",
    "EpgpRecruitList",
    "EpgpRecruitRow",
    "EpgpRecruitUpdate",
    "EpgpRecruitVoteCreate",
    "ExportAnnouncement",
    "ExportBankEntry",
    "ExportMemberNote",
    "ExportProfession",
    "ExportRecipe",
    "ExportRecruit",
    "ExportRecruitVote",
    "ExportRoster",
    "ExportRosterMember",
    "ExportSignupV2",
    "GameImportBadgeRef",
    "GameImportCharacter",
    "GameImportCrafter",
    "GameImportInactiveMember",
    "GameImportLedgerEntry",
    "GameImportLootEntry",
    "GameImportMember",
    "GameImportNews",
    "GameImportOfficerNote",
    "GameImportOfficerPart",
    "GameImportOfficerRecruit",
    "GameImportSheet",
    "GuildAnnouncementCreate",
    "GuildAnnouncementRow",
    "GuildAnnouncementsPage",
    "GuildBankPage",
    "GuildBankRow",
    "GuildBankTotals",
    "GuildCrafterProfessionCount",
    "GuildCrafterResult",
    "GuildCrafterRow",
    "GuildCrafters",
    "GuildNewsItem",
    "GuildNewsPage",
    "GuildRoster",
    "GuildRosterCharacter",
    "GuildRosterMember",
    "GuildRosterUnlinked",
    "MemberNoteImportCounts",
    "NewsKind",
    "PendingAnnouncement",
    "PendingAnnouncementsPage",
    "ProfessionImportCounts",
    "RecruitChecklist",
    "RecruitImportCounts",
    "RecruitStatus",
    "RecruitVoteChoice",
    "RosterImportCounts",
    "SignupImportCounts",
)
