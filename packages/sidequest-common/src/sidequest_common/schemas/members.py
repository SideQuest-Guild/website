"""Signed-in member profile and officer member-list schemas."""

from datetime import datetime  # pydantic needs it at runtime

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
    battletag: str | None
    roster_confirmed: bool


class MemberListing(BaseModel):
    """One row of the officers' member list (``GET /api/members``): who has signed in and what they've linked.

    Officers compare ``battletag`` against the in-game guild roster; it is never shown outside officer views.
    """

    id: int
    username: str
    display_name: str
    avatar_url: str | None
    is_guild_member: bool
    is_officer: bool
    battletag: str | None
    roster_confirmed: bool
    last_login_at: datetime | None
