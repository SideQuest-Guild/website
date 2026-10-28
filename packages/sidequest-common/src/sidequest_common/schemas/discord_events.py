"""Two-way guild event <-> Discord scheduled event sync: the bot-facing contract.

The API decides *what* Discord should show (``DiscordEventPush``); the bot does every Discord call and reports back
what Discord actually holds (``DiscordEventState``). See ``sidequest_common.models.events.GuildEvent`` for the hash
columns that keep the two sides from echoing each other.
"""

from datetime import datetime  # pydantic needs it at runtime
from enum import StrEnum
from typing import Literal
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, Field


class DiscordEventStatus(StrEnum):
    """A Discord scheduled event's status, named the way Discord's ``EventStatus`` is."""

    SCHEDULED = "scheduled"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DiscordEventState(BaseModel):
    """What Discord currently holds for one scheduled event, as the bot read it (gateway payload or REST response)."""

    id: int
    name: str
    description: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    status: DiscordEventStatus
    location: str | None = Field(default=None, description="External events only.")
    channel_id: int | None = Field(default=None, description="Voice/stage events only.")


PushAction = Literal["upsert", "cancel", "complete"]
"""``upsert``: create the event if ``discord_event_id`` is ``None`` (or it no longer exists), else edit it.
``cancel``: cancel a scheduled event (end an active one). ``complete``: end an active event, delete a scheduled one.
After ``cancel``/``complete`` the bot acks with ``event=None``: the guild event is no longer linked."""


class DiscordEventPush(BaseModel):
    """One guild event whose Discord event is out of date. Fields are Discord-ready (within Discord's limits)."""

    event_id: UUID
    discord_event_id: int | None
    action: PushAction
    name: str = Field(max_length=100)
    description: str = Field(max_length=1000)
    location: str = Field(max_length=100, description="Used for external events; voice/stage events keep theirs.")
    starts_at: datetime
    ends_at: datetime = Field(description="Discord requires an end for external events.")
    push_hash: str


class DiscordSyncPending(BaseModel):
    """``GET /api/guilds/{guild_id}/event-sync``: everything the bot should write to Discord now."""

    pushes: list[DiscordEventPush]
    deletions: list[int] = Field(description="Discord event ids whose guild event was deleted on the site.")


class DiscordPushAck(BaseModel):
    """``POST /api/guilds/{guild_id}/event-sync/{event_id}/ack``: the bot applied ``push_hash``.

    ``event`` is what Discord returned, or ``None`` when no Discord event is linked any more (ended, deleted, or the
    push was skipped because the start time had passed).
    """

    push_hash: str
    event: DiscordEventState | None


class DiscordEventReconcile(BaseModel):
    """``POST /api/guilds/{guild_id}/event-sync/reconcile``: every scheduled event currently in the guild.

    Applied like individual updates, then any linked guild event whose event isn't listed is treated as deleted in
    Discord, and any tombstone whose event isn't listed is dropped.
    """

    events: list[DiscordEventState]
