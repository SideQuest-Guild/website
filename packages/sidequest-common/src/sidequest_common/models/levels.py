"""Member XP, the ledger of one-off XP grants, and level reward roles."""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime
from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import GUID, DateTimeUTC
from sqlalchemy import BigInteger, Index, Integer, String, UniqueConstraint
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


class XPGrant(UUIDAuditBase):
    """One one-off XP grant, so attending an event or finishing a group pays out once per member.

    ``source`` is an ``XPSource`` value (``event`` or ``group``) and ``source_id`` the event's or group session's id.
    Rows are kept after the event or session is deleted, so a re-synced grant can't pay twice.
    """

    __tablename__ = "xp_grant"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", "source", "source_id", name="uq_xp_grant_once"),
        {"comment": "XP paid once per member for an attended event or a finished LFG group."},
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source: Mapped[str] = mapped_column(String(10))
    source_id: Mapped[UUID] = mapped_column(GUID)
    amount: Mapped[int] = mapped_column(Integer)
