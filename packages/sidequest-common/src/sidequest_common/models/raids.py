"""Raid events and member signups."""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime
from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

RAID_STATUSES = ("scheduled", "cancelled", "completed")
SIGNUP_ROLES = ("tank", "healer", "dps")
SIGNUP_STATUSES = ("signed", "tentative", "absent")
WOW_CLASSES = (
    "warrior",
    "paladin",
    "hunter",
    "rogue",
    "priest",
    "shaman",
    "mage",
    "warlock",
    "druid",
)


class Raid(UUIDAuditBase):
    """One scheduled raid night."""

    __tablename__ = "raid"
    __table_args__ = {"comment": "Scheduled raid events."}

    title: Mapped[str] = mapped_column(Text)
    instance: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class RaidSignup(UUIDAuditBase):
    """One member's signup for one raid. ``class`` is a Python keyword, so the column is ``wow_class``."""

    __tablename__ = "raid_signup"
    __table_args__ = (
        UniqueConstraint("raid_id", "member_id", name="uq_raid_signup_raid_member"),
        {"comment": "Member signups for a raid, including the officer-assigned raid chart (group/bench)."},
    )

    raid_id: Mapped[UUID] = mapped_column(ForeignKey("raid.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id", ondelete="CASCADE"), index=True)
    character: Mapped[str] = mapped_column(String(24))
    wow_class: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default="signed")
    comment: Mapped[str | None] = mapped_column(String(200), default=None)
    raid_group: Mapped[int | None] = mapped_column("raid_group", Integer, default=None)
    bench: Mapped[bool] = mapped_column(Boolean, default=False)
