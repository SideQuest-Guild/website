"""Schema for the bot's weekly-board week-range event listing."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sidequest_common.schemas.events import EventKind


class WeeklyBoardEvent(BaseModel):
    """One scheduled event for the weekly board post."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: EventKind
    title: str
    starts_at: datetime
    discord_thread_id: int | None
