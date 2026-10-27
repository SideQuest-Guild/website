"""Signed-in member profile schema."""

from pydantic import BaseModel, ConfigDict


class Me(BaseModel):
    """The signed-in member's profile, as returned by ``GET /api/me``.

    ``display_name`` is the guild nick, else the Discord global name, else the username. Discord ids are
    returned as strings because they're 64-bit and JSON numbers aren't safe past 2**53.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    discord_id: str
    username: str
    display_name: str
    avatar_url: str | None
    is_guild_member: bool
    is_officer: bool
