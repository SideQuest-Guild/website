"""Discord's public server widget, trimmed for signed-in members: who's online right now, by name."""

from pydantic import BaseModel

DiscordOnlineStatus = str
"""One of ``"online"``, ``"idle"`` or ``"dnd"``, as reported by Discord's widget."""


class DiscordOnlineMember(BaseModel):
    """One member from the widget's anonymized roster."""

    name: str
    """Display name (Discord calls this ``username`` on the widget, but it's the server nick/display name)."""
    status: DiscordOnlineStatus
    avatar_url: str | None
    """``cdn.discordapp.com/widget-avatars/...``; ``None`` if Discord didn't report one."""
    activity: str | None
    """The member's current activity/game name, if any."""


class DiscordOnline(BaseModel):
    """``GET /api/discord/online`` (members only): the guild widget's live roster, or empty if Discord didn't answer."""

    presence_count: int | None
    members: list[DiscordOnlineMember]
    ok: bool
    """``False`` when the widget fetch failed or timed out; ``members`` is then always empty."""
