"""EPGP loot system schemas.

Rules constants, the addon export/import wire shapes, and the HTTP API's request/response schemas
(``local://addon-contract.md`` is the source of truth; field names and string prefixes here are binding).
"""

from datetime import datetime  # pydantic needs it at runtime
from enum import StrEnum
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sidequest_common.schemas.events import EventKind, SignupRole, SignupStatus, WowClass
from sidequest_common.schemas.guild_hub import (
    MAX_ANNOUNCEMENTS_V2,
    MAX_BANK_ENTRIES,
    MAX_MEMBER_NOTES_V2,
    MAX_PROFESSION_PAIRS,
    MAX_RECRUITS_V2,
    MAX_SIGNUPS_V2,
    AnnouncementImportCounts,
    BankImportCounts,
    ExportAnnouncement,
    ExportBankEntry,
    ExportMemberNote,
    ExportProfession,
    ExportRecruit,
    ExportRoster,
    ExportSignupV2,
    GameImportCrafter,
    GameImportMember,
    GameImportNews,
    GameImportOfficerPart,
    GameImportSheet,
    MemberNoteImportCounts,
    ProfessionImportCounts,
    RecruitImportCounts,
    RosterImportCounts,
    SignupImportCounts,
)

# --- Rules constants (the site owns these numbers; they ship in the SQI1 import string's ``rules`` object) -------

EP_VALUES: dict[str, int] = {"boss_kill": 10, "progress": 10, "on_time": 5, "full_night": 5}
"""EP awarded per ``AwardReason``. ``standby`` earns the same as the raid (``on_time``/``full_night``/boss kills)."""

GP_BY_INVTYPE: dict[str, int] = {
    "INVTYPE_HEAD": 100,
    "INVTYPE_CHEST": 100,
    "INVTYPE_ROBE": 100,
    "INVTYPE_LEGS": 100,
    "INVTYPE_SHOULDER": 75,
    "INVTYPE_HAND": 75,
    "INVTYPE_WAIST": 75,
    "INVTYPE_FEET": 75,
    "INVTYPE_NECK": 55,
    "INVTYPE_WRIST": 55,
    "INVTYPE_CLOAK": 55,
    "INVTYPE_FINGER": 55,
    "INVTYPE_HOLDABLE": 55,
    "INVTYPE_SHIELD": 55,
    "INVTYPE_TRINKET": 125,
    "INVTYPE_WEAPON": 150,
    "INVTYPE_WEAPONMAINHAND": 150,
    "INVTYPE_WEAPONOFFHAND": 150,
    "INVTYPE_2HWEAPON": 200,
    "INVTYPE_RANGED": 50,
    "INVTYPE_RANGEDRIGHT": 50,
    "INVTYPE_THROWN": 50,
    "INVTYPE_RELIC": 50,
}
"""GP by ``INVTYPE_*`` at main-spec cost. A 1H "main caster weapon" uses the 2H cost (200) by officer toggle; tier
tokens use the cost of the slot the officer picks; chase items are ``slot cost * CHASE_MULTIPLIER``; legendary
pieces are flat ``LEGENDARY_GP``. None of those three cases key off ``inv_type`` alone, so they aren't in this map.
"""

CHASE_MULTIPLIER = 1.5
LEGENDARY_GP = 300
OS_PERCENT = 10
"""Off-spec pays this percent of main-spec GP, rounded half up. Alt fill and disenchant/bank pay 0."""
BASE_GP = 100
MIN_GP = 100
DECAY_PERCENT = 15
"""Weekly decay applied to EP and GP at every reset, read-time only (``amount * (1 - DECAY_PERCENT/100) ** resets``)."""
TRIAL_DAYS = 14
WEEKLY_RESET_WEEKDAY = 1
"""``datetime.weekday()`` value for Tuesday."""
WEEKLY_RESET_HOUR_UTC = 15

DEFAULT_REALM = "Whitemane"
"""The guild's single WoW: Forever realm, used when a member claims a character without specifying one."""
AWARD_AMOUNT_MIN = -1000
AWARD_AMOUNT_MAX = 1000
MAX_NAME_LENGTH = 64
MAX_NOTE_LENGTH = 200
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_SESSIONS = 50
MAX_ENCOUNTERS = 500
MAX_LOOT = 1000
MAX_AWARDS = 20000

EPGP_RULES: dict[str, object] = {
    "ep": dict(EP_VALUES),
    "gp": dict(GP_BY_INVTYPE),
    "chase_multiplier": CHASE_MULTIPLIER,
    "legendary_gp": LEGENDARY_GP,
    "os_percent": OS_PERCENT,
    "base_gp": BASE_GP,
    "min_gp": MIN_GP,
    "decay_percent": DECAY_PERCENT,
    "trial_days": TRIAL_DAYS,
}
"""Exact shape of the ``rules`` object in the ``SQI1:`` import string."""


# --- Enums ----------------------------------------------------------------------------------------------------


class LootResponse(StrEnum):
    """How a character rolled on an item."""

    MS = "ms"
    OS = "os"
    ALT = "alt"
    COUNCIL = "council"
    DE = "de"
    BANK = "bank"


class AwardReason(StrEnum):
    """Why an EP/GP ledger entry was written."""

    BOSS_KILL = "boss_kill"
    PROGRESS = "progress"
    ON_TIME = "on_time"
    FULL_NIGHT = "full_night"
    STANDBY = "standby"
    LOOT = "loot"
    ADJUST = "adjust"


class LedgerKind(StrEnum):
    """Whether a ledger entry is an EP or GP change."""

    EP = "ep"
    GP = "gp"


class LedgerSource(StrEnum):
    """Where a ledger entry came from: the addon export, or a site-made officer adjustment."""

    ADDON = "addon"
    SITE = "site"


class CharacterSource(StrEnum):
    """How a ``WowCharacter`` got linked to a member."""

    CLAIM = "claim"
    OFFICER = "officer"
    SIGNUP = "signup"
    IMPORT = "import"


class RaidStatus(StrEnum):
    """EPGP roster status, settable by an officer (``PUT /api/epgp/roster/{member_id}``)."""

    TRIAL = "trial"
    RAIDER = "raider"


# --- Addon export (``SQX1:`` + base64 JSON): the inbound payload the import service validates ---------------------


class ExportSessionMember(BaseModel):
    """One session member entry in the export payload.

    ``class`` arrives as the addon's uppercase token (e.g. ``"MAGE"``, Blizzard's ``UnitClass`` return),
    normalized to lowercase before validation.
    """

    model_config = ConfigDict(populate_by_name=True)

    character: str = Field(max_length=MAX_NAME_LENGTH)
    wow_class: WowClass | None = Field(default=None, alias="class")
    first_seen: int
    last_seen: int
    standby: bool = False

    @field_validator("wow_class", mode="before")
    @classmethod
    def _normalize_class(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value


class ExportSession(BaseModel):
    """One raid session entry in the export payload.

    Lua json encoders drop nil keys rather than emitting null, so every nullable contract field here is a pydantic
    default, not a required key: the addon may omit ``event_id``/``ended_at`` entirely (e.g. a session exported
    before the raid ended) rather than sending them as JSON ``null``.
    """

    id: str = Field(max_length=120)
    event_id: UUID | None = None
    instance_name: str = Field(max_length=120)
    instance_id: int
    difficulty_id: int
    size: int
    started_at: int
    ended_at: int | None = None
    members: list[ExportSessionMember] = Field(default_factory=list)


class ExportEncounter(BaseModel):
    """One boss pull entry in the export payload. ``session_id``/``ended_at`` may be absent (see ``ExportSession``)."""

    id: str = Field(max_length=120)
    session_id: str | None = None
    encounter_id: int
    name: str = Field(max_length=120)
    size: int
    difficulty_id: int
    success: bool
    started_at: int
    ended_at: int | None = None
    characters: list[str] = Field(default_factory=list)
    standby: list[str] = Field(default_factory=list)


class ExportLoot(BaseModel):
    """One loot award entry in the export payload."""

    id: str = Field(max_length=120)
    session_id: str | None = None
    encounter_row_id: str | None = None
    item_id: int
    item_name: str = Field(max_length=120)
    quality: int
    inv_type: str = Field(max_length=30)
    character: str = Field(max_length=MAX_NAME_LENGTH)
    response: LootResponse
    gp: int = Field(ge=AWARD_AMOUNT_MIN, le=AWARD_AMOUNT_MAX, description="Gear points (GP) this item cost.")
    at: int
    officer: str = Field(max_length=MAX_NAME_LENGTH)
    voided: bool = False


class ExportAward(BaseModel):
    """One EP/GP ledger entry in the export payload."""

    id: str = Field(max_length=120)
    session_id: str | None = None
    kind: LedgerKind
    character: str = Field(max_length=MAX_NAME_LENGTH)
    amount: int = Field(ge=AWARD_AMOUNT_MIN, le=AWARD_AMOUNT_MAX, description="EP or GP change, as set by kind.")
    reason: AwardReason
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    loot_id: str | None = None
    at: int
    officer: str = Field(max_length=MAX_NAME_LENGTH)
    voided: bool = False


class ExportPayload(BaseModel):
    """The full decoded ``SQX1:`` payload, bounded per the contract.

    ``v: 2`` adds the guild-hub sections below; every v2 section is optional so a ``v: 1`` addon keeps working
    unchanged.
    """

    v: int
    addon_version: str
    exported_at: int
    guild: str
    realm: str
    recorder: str = Field(max_length=MAX_NAME_LENGTH)
    sessions: list[ExportSession] = Field(default_factory=list, max_length=MAX_SESSIONS)
    encounters: list[ExportEncounter] = Field(default_factory=list, max_length=MAX_ENCOUNTERS)
    loot: list[ExportLoot] = Field(default_factory=list, max_length=MAX_LOOT)
    awards: list[ExportAward] = Field(default_factory=list, max_length=MAX_AWARDS)
    roster: ExportRoster | None = None
    professions: list[ExportProfession] = Field(default_factory=list, max_length=MAX_PROFESSION_PAIRS)
    signups: list[ExportSignupV2] = Field(default_factory=list, max_length=MAX_SIGNUPS_V2)
    bank: list[ExportBankEntry] = Field(default_factory=list, max_length=MAX_BANK_ENTRIES)
    announcements: list[ExportAnnouncement] = Field(default_factory=list, max_length=MAX_ANNOUNCEMENTS_V2)
    recruits: list[ExportRecruit] = Field(default_factory=list, max_length=MAX_RECRUITS_V2)
    member_notes: list[ExportMemberNote] = Field(default_factory=list, max_length=MAX_MEMBER_NOTES_V2)


# --- Site import (``SQI1:`` + base64 JSON): the outbound payload the game-import endpoint builds ------------------


class GameImportSignup(BaseModel):
    """One event sign-up in the game-import payload. ``character`` is the free-text sign-up name, no realm."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    character: str
    wow_class: WowClass = Field(alias="class")
    role: SignupRole
    status: SignupStatus
    group: int | None
    bench: bool


class GameImportEvent(BaseModel):
    """One upcoming scheduled event in the game-import payload."""

    id: UUID
    title: str
    kind: EventKind
    starts_at: int
    size: int | None
    signups: list[GameImportSignup]


class GameImportStandingsRow(BaseModel):
    """One standings row in the game-import payload."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    member_id: int | None
    name: str
    main: str | None
    wow_class: WowClass | None = Field(alias="class")
    characters: list[str]
    ep: float = Field(description="Effort points (EP, shown as Renown on the site).")
    gp: float = Field(description="Gear points (GP).")
    pr: float = Field(description="Priority: EP divided by GP.")
    trial: bool


class GameImportPayload(BaseModel):
    """The full ``SQI1:`` payload built by ``GET /api/epgp/game-import``.

    ``members``/``news`` are the public part (the addon may broadcast them); ``sheets``/``crafters``/
    ``recipe_names`` are on-demand (an officer's addon answers members' requests, never broadcasts the whole
    thing); ``officer`` stays on officers' addons only. All four v2 additions are always present since the
    endpoint already requires an officer.
    """

    v: int
    generated_at: int
    rules: dict
    standings: list[GameImportStandingsRow]
    killed_encounters: list[int]
    events: list[GameImportEvent]
    members: list[GameImportMember] = Field(default_factory=list)
    news: list[GameImportNews] = Field(default_factory=list)
    sheets: dict[str, GameImportSheet] = Field(default_factory=dict)
    crafters: list[GameImportCrafter] = Field(default_factory=list)
    recipe_names: dict[str, str] = Field(default_factory=dict)
    officer: GameImportOfficerPart


# --- HTTP API schemas -----------------------------------------------------------------------------------------


class EpgpImportBody(BaseModel):
    """Body for ``POST /api/epgp/imports``: any text containing one ``SQX1:`` string."""

    payload: str


class ImportCounts(BaseModel):
    """New vs. updated (re-imported, unchanged ``external_id``) row counts."""

    new: int = 0
    updated: int = 0


class LootImportCounts(ImportCounts):
    """``ImportCounts`` plus rows newly voided by this import."""

    voided: int = 0


class AwardImportCounts(ImportCounts):
    """``ImportCounts`` plus rows newly voided by this import."""

    voided: int = 0


class ImportAttendanceResult(BaseModel):
    """What the attendance hand-off did for one import call."""

    event_id: UUID | None
    marked: int = 0


class EpgpImportResult(BaseModel):
    """Response for ``POST /api/epgp/imports``."""

    recorder: str
    sessions: ImportCounts
    encounters: ImportCounts
    loot: LootImportCounts
    awards: AwardImportCounts
    unlinked_characters: list[str] = Field(default_factory=list)
    attendance: ImportAttendanceResult
    conflicts: list[str] = Field(default_factory=list)
    """Session external ids skipped by the one-recorder-per-raid-night conflict rule."""
    roster: RosterImportCounts = Field(default_factory=RosterImportCounts)
    professions: ProfessionImportCounts = Field(default_factory=ProfessionImportCounts)
    signups: SignupImportCounts = Field(default_factory=SignupImportCounts)
    bank: BankImportCounts = Field(default_factory=BankImportCounts)
    announcements: AnnouncementImportCounts = Field(default_factory=AnnouncementImportCounts)
    recruits: RecruitImportCounts = Field(default_factory=RecruitImportCounts)
    member_notes: MemberNoteImportCounts = Field(default_factory=MemberNoteImportCounts)


class EpgpRules(BaseModel):
    """The ``rules`` object as returned by ``GET /api/epgp/standings`` (same shape as the game-import payload)."""

    ep: dict[str, int] = Field(description="Effort points (EP) awarded per AwardReason.")
    gp: dict[str, int] = Field(description="Gear points (GP) by Discord item inventory type at main-spec cost.")
    chase_multiplier: float
    legendary_gp: int
    os_percent: int
    base_gp: int
    min_gp: int
    decay_percent: int
    trial_days: int


class EpgpStandingsRow(BaseModel):
    """One row of ``GET /api/epgp/standings``."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    member_id: int | None
    name: str
    main: str | None
    wow_class: WowClass | None = Field(alias="class")
    characters: list[str]
    ep: float = Field(description="Effort points (EP, shown as Renown on the site).")
    gp: float = Field(description="Gear points (GP).")
    pr: float = Field(description="Priority: EP divided by GP.")
    trial: bool


class EpgpStandings(BaseModel):
    """Response for ``GET /api/epgp/standings`` (public)."""

    generated_at: datetime
    rules: EpgpRules
    rows: list[EpgpStandingsRow]


class EpgpLedgerRow(BaseModel):
    """One row of ``GET /api/epgp/ledger``."""

    id: UUID
    at: datetime
    kind: LedgerKind
    amount: int = Field(description="EP or GP change, as set by kind.")
    decayed: float = Field(description="The amount after weekly decay has been applied, read-time only.")
    reason: str
    note: str | None
    character: str | None
    member_id: int | None
    member_name: str | None
    officer: str
    item_name: str | None
    voided: bool


class EpgpLedgerPage(BaseModel):
    """Response for ``GET /api/epgp/ledger`` (public), newest first."""

    entries: list[EpgpLedgerRow]


class EpgpLootRow(BaseModel):
    """One row of ``GET /api/epgp/loot``."""

    id: UUID
    at: datetime
    item_id: int
    item_name: str
    quality: int
    character: str | None
    member_id: int | None
    member_name: str | None
    response: LootResponse
    gp: int = Field(description="Gear points (GP) this item cost.")
    instance_name: str | None
    encounter_name: str | None
    voided: bool


class EpgpLootPage(BaseModel):
    """Response for ``GET /api/epgp/loot`` (public), newest first."""

    items: list[EpgpLootRow]


class EpgpProgressionEncounter(BaseModel):
    """One boss's kill/wipe tally on the progression board."""

    encounter_id: int
    name: str
    first_kill_at: datetime | None
    kills: int
    wipes: int
    last_attempt_at: datetime


class EpgpProgressionInstance(BaseModel):
    """One instance's bosses on the progression board."""

    instance_id: int
    name: str
    size: int
    encounters: list[EpgpProgressionEncounter]


class EpgpProgression(BaseModel):
    """Response for ``GET /api/epgp/progression`` (public)."""

    instances: list[EpgpProgressionInstance]


class EpgpGameImport(BaseModel):
    """Response for ``GET /api/epgp/game-import`` (officer)."""

    payload: str
    generated_at: datetime


class EpgpAdjustmentCreate(BaseModel):
    """Body for ``POST /api/epgp/adjustments`` (officer)."""

    member_id: int
    kind: LedgerKind
    amount: int = Field(ge=AWARD_AMOUNT_MIN, le=AWARD_AMOUNT_MAX, description="EP or GP change, as set by kind.")
    reason: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)


class EpgpCharacter(BaseModel):
    """A ``WowCharacter``, as returned by the characters admin screen and ``/api/me/characters``."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    id: UUID
    name: str
    realm: str
    wow_class: WowClass | None = Field(alias="class")
    member_id: int | None
    member_name: str | None
    is_main: bool
    source: CharacterSource
    last_seen_at: datetime | None


class EpgpCharacterList(BaseModel):
    """Response for ``GET /api/epgp/characters`` (officer) and ``GET /api/me/characters`` (member)."""

    characters: list[EpgpCharacter]


class EpgpCharacterUpdate(BaseModel):
    """Body for ``PUT /api/epgp/characters/{id}`` (officer)."""

    member_id: int | None
    is_main: bool


class MyCharacterCreate(BaseModel):
    """Body for ``POST /api/me/characters`` (member). 409 if another member already claimed this name-realm."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=2, max_length=MAX_NAME_LENGTH)
    realm: str | None = None
    wow_class: WowClass | None = Field(default=None, alias="class")


class EpgpRosterRow(BaseModel):
    """One row of ``GET /api/epgp/roster`` (officer)."""

    member_id: int
    name: str
    raid_status: RaidStatus | None
    trial_started_at: datetime | None


class EpgpRoster(BaseModel):
    """Response for ``GET /api/epgp/roster`` (officer)."""

    members: list[EpgpRosterRow]


class EpgpRosterUpdate(BaseModel):
    """Body for ``PUT /api/epgp/roster/{member_id}`` (officer). Setting ``"trial"`` stamps ``trial_started_at`` now."""

    raid_status: RaidStatus | None


class EpgpSyncTokenSummary(BaseModel):
    """One non-revoked sync token, without the secret (``GET /api/epgp/sync-tokens``, officer, own tokens only)."""

    id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


class EpgpSyncTokenList(BaseModel):
    """Response for ``GET /api/epgp/sync-tokens`` (officer)."""

    tokens: list[EpgpSyncTokenSummary]


class EpgpSyncTokenCreate(BaseModel):
    """Body for ``POST /api/epgp/sync-tokens`` (officer)."""

    name: str = Field(min_length=1, max_length=60)


class EpgpSyncTokenCreated(BaseModel):
    """Response for ``POST /api/epgp/sync-tokens``: the token shown once, never stored in plaintext."""

    id: UUID
    name: str
    token: str


MAX_DEVICE_NAME_LENGTH = 60
"""Cap on ``EpgpDeviceAuthorizationCreate.device_name``, trimmed; also the sync token name length it feeds into."""

_LAST_CONTROL_CHAR = 0x1F
_DEL_CHAR = 0x7F


class DeviceAuthorizationPollStatus(StrEnum):
    """``status`` on ``POST /api/epgp/device-authorizations/token``."""

    PENDING = "pending"
    SLOW_DOWN = "slow_down"
    DENIED = "denied"
    EXPIRED = "expired"
    APPROVED = "approved"


class DeviceAuthorizationStatus(StrEnum):
    """``status`` on ``GET /api/epgp/device-authorizations/{user_code}``."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class EpgpDeviceAuthorizationCreate(BaseModel):
    """Body for ``POST /api/epgp/device-authorizations`` (public): the device starting a browser sign-in."""

    device_name: str = Field(min_length=1, max_length=MAX_DEVICE_NAME_LENGTH)

    @field_validator("device_name")
    @classmethod
    def _validate_device_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            msg = "device_name must not be blank"
            raise ValueError(msg)
        if any(ord(char) <= _LAST_CONTROL_CHAR or ord(char) == _DEL_CHAR for char in trimmed):
            msg = "device_name must not contain control characters"
            raise ValueError(msg)
        return trimmed


class EpgpDeviceAuthorizationCreated(BaseModel):
    """Response for ``POST /api/epgp/device-authorizations`` (public): poll ``.../token`` with ``device_code``."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class EpgpDeviceAuthorizationPoll(BaseModel):
    """Body for ``POST /api/epgp/device-authorizations/token`` (public)."""

    device_code: str


class EpgpDeviceAuthorizationPollResult(BaseModel):
    """Response for ``POST /api/epgp/device-authorizations/token`` (public): always 200, never an oracle.

    ``token``/``name`` are set only once, on the first ``"approved"`` poll; a later poll for the same device code
    gets ``"expired"``.
    """

    status: DeviceAuthorizationPollStatus
    token: str | None = None
    name: str | None = None


class EpgpDeviceAuthorizationStatus(BaseModel):
    """Response for ``GET /api/epgp/device-authorizations/{user_code}`` (any guild member)."""

    user_code: str
    device_name: str
    created_at: datetime
    expires_at: datetime
    status: DeviceAuthorizationStatus


class EpgpSyncTokenMe(BaseModel):
    """Response for ``GET /api/epgp/sync-tokens/me`` (Bearer only).

    What the presenting token's owner can see about themselves. ``is_guild_member`` is always ``true``: a token
    whose owner left the guild gets 403 instead.
    """

    display_name: str
    avatar_url: str | None
    is_officer: bool
    is_guild_member: bool
    calendar_url: str | None
    token_name: str
