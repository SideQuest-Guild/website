"""Member-declared away date ranges, used to grant a Discord role and to flag event rosters."""

from datetime import date  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy import BigInteger, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column


class MemberAwayRange(UUIDAuditBase):
    """One inclusive date range (``start_date``..``end_date``) a member marked themselves away for.

    Past ranges (``end_date`` before today, America/Chicago) are pruned on read rather than kept indefinitely.
    """

    __tablename__ = "member_away_range"
    __table_args__ = {"comment": "Member-declared away date ranges (inclusive)."}

    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("member.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(String(100), default=None)
