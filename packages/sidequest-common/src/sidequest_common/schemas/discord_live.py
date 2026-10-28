"""Live Discord presence/voice-channel status, counts only (never names or ids)."""

from datetime import datetime

from pydantic import BaseModel, Field


class VoiceChannelCount(BaseModel):
    """One voice/stage channel the bot reported on."""

    name: str
    """Discord channel name as shown, e.g. "dungeon-1", "Lobby"."""
    count: int = Field(ge=0)
    """Non-bot members connected right now."""


class DiscordLiveReport(BaseModel):
    """Bot -> API: what the guild looks like right now."""

    online: int | None = None
    """``Guild.approximate_presence_count`` (``None`` if the fetch failed)."""
    members: int | None = None
    """``Guild.approximate_member_count``."""
    voice: list[VoiceChannelCount]
    """Every voice/stage channel ``@everyone`` can view, zero counts included, in Discord's channel order."""


class DiscordLive(BaseModel):
    """API -> website (public): the guild's live status, or empty if the bot hasn't reported recently."""

    online: int | None
    members: int | None
    voice: list[VoiceChannelCount]
    reported_at: datetime | None
    """When the bot last reported."""
