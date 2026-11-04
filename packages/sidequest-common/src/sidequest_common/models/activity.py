"""Hourly per-member activity counts, for server stats and Hall of Heroes profile charts."""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import BigInteger, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class MemberActivityHour(UUIDAuditBase):
    """One member's activity in one UTC hour.

    ``messages`` is XP-eligible chat messages (what the bot sends to the chat-XP route), bumped once per
    ``award_xp`` call regardless of whether XP was actually paid. ``voice_minutes`` is minutes present under the
    stats voice rule (any voice/stage channel but the guild's AFK channel, with at least two non-bot members),
    looser than and separate from the voice-XP rule; it is recorded even while leveling is disabled.
    ``chat_xp``/``voice_xp`` are the XP actually awarded that hour, which can be less than a full award (or zero)
    when leveling was off or the chat cooldown was active.
    """

    __tablename__ = "member_activity_hour"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", "hour_start", name="uq_member_activity_hour"),
        Index("ix_member_activity_hour_guild_hour", "guild_id", "hour_start"),
        {"comment": "Hourly per-member message/voice/XP counts, for stats and Hall of Heroes profiles."},
    )

    guild_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    hour_start: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    messages: Mapped[int] = mapped_column(Integer, default=0)
    voice_minutes: Mapped[int] = mapped_column(Integer, default=0)
    chat_xp: Mapped[int] = mapped_column(Integer, default=0)
    voice_xp: Mapped[int] = mapped_column(Integer, default=0)
