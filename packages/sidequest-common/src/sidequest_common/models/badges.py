"""Earned Hall of Heroes badges.

Badge definitions (id, name, description, icon, Discord role color) live in code
(``sidequest_common.schemas.badges.BADGES``); this table only records who earned which one and when. Most badges
are permanent once earned. ``top_helper`` is a moving monthly title: the service deletes/recreates this row for a
new member instead of keeping history, so at most one ``top_helper`` row exists at a time. Rows are deleted with
the member's account (``ondelete="CASCADE"``).
"""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class MemberBadge(UUIDAuditBase):
    """One badge earned by one member."""

    __tablename__ = "member_badge"
    __table_args__ = (
        UniqueConstraint("member_id", "badge_id", name="uq_member_badge_member_badge"),
        {"comment": "Hall of Heroes badges earned by members; granted/synced server-side, idempotent."},
    )

    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("member.id", ondelete="CASCADE"), index=True)
    badge_id: Mapped[str] = mapped_column(String(40), index=True)
    earned_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    announced_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
