"""Discord role names, pushed by the bot so the GM console can show role tags on members."""

from pydantic import BaseModel, Field


class GuildRoleIn(BaseModel):
    """One Discord role, as reported by the bot."""

    id: int
    name: str
    color: int = Field(ge=0)
    position: int
    managed: bool


class GuildRolesReplace(BaseModel):
    """Body for ``PUT /api/guilds/{guild_id}/roles``: the guild's full current role set."""

    roles: list[GuildRoleIn]
