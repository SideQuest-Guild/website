"""Member XP and level reward roles."""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import BigInteger, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class MemberLevel(UUIDAuditBase):
    """Running XP total for one member in one guild."""

    __tablename__ = "member_level"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id"),
        Index("ix_member_level_guild_xp", "guild_id", "xp"),
        {"comment": "Per-member XP and level."},
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    xp: Mapped[int] = mapped_column(BigInteger, default=0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    last_xp_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)


class LevelRole(UUIDAuditBase):
    """Role granted on reaching ``level``."""

    __tablename__ = "level_role"
    __table_args__ = (
        UniqueConstraint("guild_id", "level", name="uq_level_role_guild_level"),
        UniqueConstraint("guild_id", "role_id", name="uq_level_role_guild_role"),
        {"comment": "Roles awarded at level milestones."},
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    level: Mapped[int] = mapped_column(Integer)
    role_id: Mapped[int] = mapped_column(BigInteger)
