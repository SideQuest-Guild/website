"""The guild's live Discord presence/voice status, as last reported by the bot."""

from datetime import datetime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column


class DiscordLiveStatus(UUIDAuditBase):
    """One row per guild: the bot's most recent online/member/voice-channel report."""

    __tablename__ = "discord_live_status"
    __table_args__ = {"comment": "The guild's live Discord presence/voice status, as last reported by the bot."}

    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)

    online: Mapped[int | None] = mapped_column(Integer, default=None)
    members: Mapped[int | None] = mapped_column(Integer, default=None)
    voice: Mapped[list[dict]] = mapped_column(JsonB, default=list)
    reported_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
