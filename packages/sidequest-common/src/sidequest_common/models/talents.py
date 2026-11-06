"""Talent builds members save from the talent calculator, and the ones officers pin for raids."""

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class TalentBuild(UUIDAuditBase):
    """One saved talent build for a class.

    ``code`` holds the points per talent, one digit per talent node in tree order and the three trees joined by
    ``-`` (the calculator's own encoding, which is also its share link). ``pinned`` marks a build officers recommend
    for raids; members see pinned builds next to their own.
    """

    __tablename__ = "talent_build"
    __table_args__ = {"comment": "Talent calculator builds saved by members; officers pin raid builds."}

    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("member.id", ondelete="CASCADE"), index=True)
    wow_class: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
