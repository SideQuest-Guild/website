"""Member away date ranges.

Members declare date ranges (inclusive) they'll be away on ``/account/``; the bot grants/removes the "Away on a
Quest" role (``GuildConfig.away_role_id``) for whoever's range covers today in America/Chicago
(``GET /api/guilds/{guild_id}/away-now``), and ``EventDetail.away`` flags members away on an event's start date.
"""

from datetime import date  # pydantic needs it at runtime
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AwayRangeIn(BaseModel):
    """Body for ``POST /api/me/away``."""

    start_date: date
    end_date: date
    note: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _end_not_before_start(self) -> AwayRangeIn:
        if self.end_date < self.start_date:
            msg = "end_date must be on or after start_date"
            raise ValueError(msg)
        return self


class AwayRangeSchema(BaseModel):
    """One of the signed-in member's away ranges, as returned by ``GET/POST /api/me/away``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    start_date: date
    end_date: date
    note: str | None


class AwayNowReport(BaseModel):
    """``GET /api/guilds/{guild_id}/away-now``: linked members away today (America/Chicago), bot-facing."""

    discord_ids: list[int]
