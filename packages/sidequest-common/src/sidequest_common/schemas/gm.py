"""GM console schemas: member management, moderation cases, and the merged activity log.

See ``local://gm-console-contract.md``.
"""

from datetime import datetime  # pydantic needs it at runtime
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field


class RoleTag(BaseModel):
    """A Discord role, as last reported by the bot's ``PUT /api/guilds/{guild_id}/roles``."""

    id: str
    name: str
    color: str | None
    """``#rrggbb``, ``None`` when the role has no color (Discord color ``0``)."""


class GmMember(BaseModel):
    """One member as shown in the GM console's member list/detail."""

    id: int
    discord_id: str
    username: str
    display_name: str
    avatar_url: str | None
    roles: list[RoleTag]
    is_guild_member: bool
    is_officer: bool
    is_gm: bool
    roster_confirmed_at: datetime | None
    battletag: str | None
    battlenet_linked_at: datetime | None
    first_seen_at: datetime
    last_login_at: datetime | None
    signup_count: int
    case_count: int
    level: int | None


class GmSignup(BaseModel):
    """One of a member's event sign-ups, as shown on their GM console detail page."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    event_id: UUID
    title: str
    kind: str
    starts_at: datetime
    event_status: str
    status: str
    character: str | None
    wow_class: str | None = Field(alias="class")
    role: str | None
    comment: str | None


class GmCase(BaseModel):
    """One moderation case, with Discord ids resolved to display names when known on the site."""

    case_number: int
    action: str
    user_id: str
    user_name: str | None
    moderator_id: str
    moderator_name: str | None
    reason: str | None
    duration_seconds: int | None
    created_at: datetime


class GmMemberDetail(BaseModel):
    """A member's full GM console profile."""

    member: GmMember
    signups: list[GmSignup]
    cases: list[GmCase]
    xp: int | None
    message_count: int | None


class LogActor(BaseModel):
    """Who performed a logged action, when known (officer-sourced entries only)."""

    display_name: str
    avatar_url: str | None


class LogEntry(BaseModel):
    """One row of the GM console's unified activity log."""

    id: str
    at: datetime
    kind: str
    actor: LogActor | None
    summary: str
    detail: str | None
    member_id: int | None
    event_id: UUID | None
    case_number: int | None


class LogPage(BaseModel):
    """A page of the activity log, newest first."""

    entries: list[LogEntry]
    next_before: datetime | None


class GmCaseReasonUpdate(BaseModel):
    """Body for ``PATCH /api/gm/cases/{case_number}``."""

    reason: str = Field(min_length=1, max_length=500)
