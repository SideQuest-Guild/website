"""Schemas for the bot's weekly board: the week's events and the Discord card it posts for each one."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sidequest_common.schemas.events import EventKind, SignupRole, SignupStatus, WowClass


class BoardSignup(BaseModel):
    """One member's sign-up as an event's weekly-board card lists it, in sign-up order.

    ``discord_id`` is the member to @-mention; ``class``/``role`` are only set for role kinds (raid, dungeon).
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    status: SignupStatus
    discord_id: int
    wow_class: WowClass | None = Field(default=None, alias="class")
    role: SignupRole | None = None


class WeeklyBoardEvent(BaseModel):
    """One scheduled event for the weekly board post, with what its card shows."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: EventKind
    title: str
    starts_at: datetime
    discord_thread_id: int | None
    location: str = ""
    notes: str | None = None
    signups: list[BoardSignup] = Field(default_factory=list, description="Every sign-up, in sign-up order.")


class WeeklyBoardMessage(BaseModel):
    """``PUT /api/guilds/{guild_id}/weekly-board/events/{event_id}/message``: the card the bot posted for an event.

    From then on the event-sync push carries this message and the event's sign-ups, so the bot keeps the card's
    Going/Maybe/Can't lists current.
    """

    channel_id: int
    message_id: int
