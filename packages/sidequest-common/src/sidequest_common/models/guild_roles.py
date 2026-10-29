"""Discord role names/colors/positions, replaced wholesale by the bot on its live-status loop."""

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy import BigInteger, Boolean, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class GuildRole(UUIDAuditBase):
    """One Discord role in a guild, as last reported by the bot. ``@everyone`` is excluded by the bot."""

    __tablename__ = "guild_role"
    __table_args__ = (
        UniqueConstraint("guild_id", "role_id", name="uq_guild_role_guild_role"),
        {"comment": "Discord role names/colors/positions, as last reported by the bot."},
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    managed: Mapped[bool] = mapped_column(Boolean, default=False)
