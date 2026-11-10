"""Group voice channel schemas: the bot's session reports, and the officer stats and public leaderboard.

Discord snowflakes are strings on the wire (browsers can't hold them in a JS number).
"""

from datetime import datetime  # pydantic needs it at runtime
from enum import StrEnum
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, Field

from sidequest_common.schemas.events import EventKind, SignupRole

GROUP_KINDS: tuple[EventKind, ...] = (
    EventKind.DUNGEON,
    EventKind.RAID,
    EventKind.WORLD_BOSS,
    EventKind.LEVELING,
    EventKind.PVP,
    EventKind.SOCIAL,
)
"""The kinds the ``#lfg`` panel offers, in button order. ``social`` is the panel's "Hangout"."""

GROUP_KIND_LABELS: dict[EventKind, str] = {
    EventKind.DUNGEON: "Dungeon",
    EventKind.RAID: "Raid",
    EventKind.WORLD_BOSS: "World Boss",
    EventKind.LEVELING: "Leveling",
    EventKind.PVP: "PvP",
    EventKind.SOCIAL: "Hangout",
}

GROUP_KIND_PREFIX: dict[EventKind, str] = {
    EventKind.DUNGEON: "dungeon",
    EventKind.RAID: "raid",
    EventKind.WORLD_BOSS: "boss",
    EventKind.LEVELING: "leveling",
    EventKind.PVP: "pvp",
    EventKind.SOCIAL: "hangout",
}
"""Channel name prefix: ``dungeon-1`` by default, ``dungeon-deadmines`` once named."""

GROUP_KIND_DEFAULT_CAP: dict[EventKind, int | None] = {
    EventKind.DUNGEON: 5,
    EventKind.RAID: 40,
    EventKind.WORLD_BOSS: 40,
    EventKind.LEVELING: 5,
    EventKind.PVP: None,
    EventKind.SOCIAL: None,
}
"""Voice user limit a new channel gets; ``None`` is no limit. The owner can change it."""

MAX_GROUP_CAP = 99
"""Discord's voice channel user limit ceiling."""

MAX_LIVE_GROUPS = 15
"""Group channels allowed at once across the server."""

EMPTY_GRACE_SECONDS = 120
"""How long a group channel may sit empty (or unjoined after creation) before it is torn down."""

COUNTED_GROUP_MINUTES = 10
"""A session counts toward stats once two or more members spent this many minutes in it together."""

GROUP_TRANSCRIPT_RETENTION_DAYS = 30

PARTY_ANIMAL_THRESHOLD = 50
"""Counted groups a member must take part in (10+ minutes each) for the Party Animal badge."""

PARTY_LEADER_THRESHOLD = 25
"""Counted groups a member must start for the Party Leader badge."""

MAX_GROUP_NAME_LENGTH = 80
MAX_GROUP_NOTE_LENGTH = 200
MAX_TRANSCRIPT_MESSAGES = 2000


class GroupEndReason(StrEnum):
    """Why a group channel was torn down."""

    EMPTY = "empty"
    """Everyone left and it stayed empty for ``EMPTY_GRACE_SECONDS``."""
    UNJOINED = "unjoined"
    """Nobody joined within ``EMPTY_GRACE_SECONDS`` of creation."""
    OWNER = "owner"
    """The owner pressed End."""
    LOST = "lost"
    """The channel disappeared (deleted by hand, or gone when the bot came back up)."""


class GroupMemberMinutes(BaseModel):
    """One member's cumulative minutes in a group channel, so far."""

    discord_id: str
    display_name: str = Field(max_length=100)
    minutes: int = Field(ge=0)


class GroupPairMinutes(BaseModel):
    """Cumulative minutes two members spent in a group channel together. ``discord_id_a < discord_id_b``."""

    discord_id_a: str
    discord_id_b: str
    minutes: int = Field(ge=0)


class GroupPresenceReport(BaseModel):
    """Bot -> API: a group channel's cumulative presence so far.

    Idempotent like ``VoicePresenceReport``: every number is stored as ``max(existing, reported)``, so the bot can
    push repeatedly, including after a restart resumed its counters from ``GroupSessionSchema``.
    """

    peak_size: int = Field(ge=0)
    grouped_minutes: int = Field(ge=0)
    members: list[GroupMemberMinutes] = Field(default_factory=list)
    pairs: list[GroupPairMinutes] = Field(default_factory=list)


class GroupSessionCreate(BaseModel):
    """Body for ``POST /api/guilds/{id}/groups``: the bot just created a group channel."""

    discord_channel_id: str
    channel_name: str = Field(max_length=100)
    kind: EventKind
    creator_discord_id: str
    name: str | None = Field(default=None, max_length=MAX_GROUP_NAME_LENGTH)
    note: str | None = Field(default=None, max_length=MAX_GROUP_NOTE_LENGTH)
    needs: list[SignupRole] = Field(default_factory=list)
    cap: int | None = Field(default=None, ge=1, le=MAX_GROUP_CAP)
    event_id: UUID | None = None
    card_message_id: str | None = None
    pug_role_id: str | None = None
    """Set for a PUG group: the temporary Discord role its invite grants to outside players."""


class GroupSessionUpdate(BaseModel):
    """Body for ``PATCH /api/guilds/{id}/groups/{session_id}``. Only fields sent change; send ``null`` to clear."""

    channel_name: str | None = Field(default=None, max_length=100)
    """Never cleared: ``null`` leaves it as is."""

    name: str | None = Field(default=None, max_length=MAX_GROUP_NAME_LENGTH)
    note: str | None = Field(default=None, max_length=MAX_GROUP_NOTE_LENGTH)
    needs: list[SignupRole] | None = None
    cap: int | None = Field(default=None, ge=1, le=MAX_GROUP_CAP)
    owner_discord_id: str | None = None
    card_message_id: str | None = None


class GroupTranscriptMessage(BaseModel):
    """One message from a group channel's text chat."""

    author_discord_id: str
    author_name: str = Field(max_length=100)
    content: str = Field(max_length=4000)
    created_at: datetime
    attachments: list[str] = Field(default_factory=list)
    """Attachment URLs. Discord's CDN links expire, so these are a pointer, not a copy."""


class GroupSessionClose(BaseModel):
    """Body for ``POST /api/guilds/{id}/groups/{session_id}/close``. Closing twice keeps the first close."""

    end_reason: GroupEndReason
    presence: GroupPresenceReport
    transcript: list[GroupTranscriptMessage] = Field(default_factory=list, max_length=MAX_TRANSCRIPT_MESSAGES)


class GroupSessionSchema(BaseModel):
    """A group session as the bot sees it: settings plus presence so far, so a restarted bot can resume counting."""

    id: UUID
    discord_channel_id: str
    channel_name: str
    kind: EventKind
    name: str | None
    note: str | None
    needs: list[SignupRole]
    cap: int | None
    creator_discord_id: str
    owner_discord_id: str
    event_id: UUID | None
    card_message_id: str | None
    pug_role_id: str | None = None
    started_at: datetime
    ended_at: datetime | None
    end_reason: GroupEndReason | None
    peak_size: int
    grouped_minutes: int
    members: list[GroupMemberMinutes]
    pairs: list[GroupPairMinutes]


class GroupTranscriptPurge(BaseModel):
    """Reply from ``POST /api/guilds/{id}/groups/purge``: transcripts deleted for being past retention."""

    deleted: int


class GroupPerson(BaseModel):
    """Someone on a stats list. ``member_id`` is set when they have a site account (links to their profile)."""

    discord_id: str
    display_name: str
    member_id: int | None = None


class GroupPersonStat(BaseModel):
    """One person's line on a stats list: ``value`` is minutes, groups, or partners depending on the list."""

    person: GroupPerson
    value: int
    sessions: int


class GroupDuoStat(BaseModel):
    """Two people who grouped together."""

    a: GroupPerson
    b: GroupPerson
    minutes: int
    sessions: int


class GroupKindStat(BaseModel):
    """Counted sessions and member-minutes for one kind."""

    kind: EventKind
    sessions: int
    minutes: int


class GroupInstanceStat(BaseModel):
    """How often a named group (an instance, usually) was run."""

    kind: EventKind
    name: str
    sessions: int


class GroupHourStat(BaseModel):
    """Counted sessions that started in one weekday/hour slot, America/Chicago. ``weekday`` 0 is Monday."""

    weekday: int = Field(ge=0, le=6)
    hour: int = Field(ge=0, le=23)
    sessions: int


class GroupStats(BaseModel):
    """``GET /api/groups/stats`` (officer): who groups, with whom, and what, over the last ``days`` days.

    Only counted sessions (see ``COUNTED_GROUP_MINUTES``) feed the lists; ``sessions_total`` includes the rest.
    Lists hold at most ten lines each.
    """

    days: int
    sessions_total: int
    sessions_counted: int
    grouped_minutes: int
    by_kind: list[GroupKindStat]
    top_instances: list[GroupInstanceStat]
    most_grouped: list[GroupPersonStat]
    most_social: list[GroupPersonStat]
    best_duos: list[GroupDuoStat]
    most_led: list[GroupPersonStat]
    busy_hours: list[GroupHourStat]


class GroupSessionSummary(BaseModel):
    """One line on ``GET /api/groups/sessions`` (officer)."""

    id: UUID
    kind: EventKind
    name: str | None
    channel_name: str
    creator: GroupPerson
    event_id: UUID | None
    started_at: datetime
    ended_at: datetime | None
    end_reason: GroupEndReason | None
    peak_size: int
    grouped_minutes: int
    counted: bool
    has_transcript: bool


class GroupSessionDetail(GroupSessionSummary):
    """``GET /api/groups/sessions/{id}`` (officer): one session with who was in it and its chat, if still kept."""

    note: str | None
    needs: list[SignupRole]
    members: list[GroupPersonStat]
    transcript: list[GroupTranscriptMessage] | None
    transcript_expires_at: datetime | None


class GroupLeaderboardRow(BaseModel):
    """One line on the public "most grouped" board. Only members with a site account appear."""

    member_id: int
    display_name: str
    groups: int
    minutes: int


class GroupLeaderboard(BaseModel):
    """``GET /api/groups/leaderboard`` (public): members by counted groups joined, last 30 days and all time."""

    month: list[GroupLeaderboardRow]
    all_time: list[GroupLeaderboardRow]
