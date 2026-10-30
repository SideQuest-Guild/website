"""Live Discord presence/voice-channel status, counts only (never names or ids)."""

from datetime import datetime

from pydantic import BaseModel, Field


class VoiceChannelCount(BaseModel):
    """One voice/stage channel the bot reported on."""

    name: str = Field(description='Discord channel name as shown, for example "dungeon-1" or "Lobby".')
    count: int = Field(ge=0, description="Members connected right now, not counting bots.")


class DiscordLiveReport(BaseModel):
    """Bot -> API: what the guild looks like right now."""

    online: int | None = Field(default=None, description="Guild.approximate_presence_count. None if the fetch failed.")
    members: int | None = Field(default=None, description="Guild.approximate_member_count.")
    voice: list[VoiceChannelCount] = Field(
        description="Every voice or stage channel @everyone can view, in Discord's channel order. "
        "Includes channels with zero members connected."
    )


class DiscordLive(BaseModel):
    """API -> website (public): the guild's live status, or empty if the bot hasn't reported recently."""

    online: int | None
    members: int | None
    voice: list[VoiceChannelCount]
    reported_at: datetime | None = Field(description="When the bot last reported this status.")
