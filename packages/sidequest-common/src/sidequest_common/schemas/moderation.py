"""Moderation case schemas."""

from datetime import datetime  # pydantic needs it at runtime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CaseAction(StrEnum):
    """Kinds of moderation action recorded as cases."""

    WARN = "warn"
    TIMEOUT = "timeout"
    UNTIMEOUT = "untimeout"
    KICK = "kick"
    BAN = "ban"
    UNBAN = "unban"
    AUTOMOD = "automod"


class ModCaseCreate(BaseModel):
    """Body for ``POST /cases``; the API assigns ``case_number``."""

    action: CaseAction
    user_id: int
    moderator_id: int
    reason: str | None = Field(default=None, max_length=1000)
    duration_seconds: int | None = Field(default=None, ge=0)


class ModCaseUpdate(BaseModel):
    """Body for ``PATCH /cases/{case_number}``."""

    reason: str | None = Field(default=None, max_length=1000)


class ModCaseSchema(BaseModel):
    """A recorded case."""

    model_config = ConfigDict(from_attributes=True)

    guild_id: int
    case_number: int
    action: CaseAction
    user_id: int
    moderator_id: int
    reason: str | None
    duration_seconds: int | None
    created_at: datetime
