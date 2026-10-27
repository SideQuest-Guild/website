"""Moderation case log."""

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy import BigInteger, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class ModCase(UUIDAuditBase):
    """One moderation action. ``case_number`` counts up from 1 per guild."""

    __tablename__ = "mod_case"
    __table_args__ = (
        UniqueConstraint("guild_id", "case_number"),
        {"comment": "Moderation actions (warn, timeout, kick, ban, ...)."},
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    case_number: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    moderator_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
