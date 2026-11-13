"""Recruitment drive persistence: the in-game guild log and per-recruit qualification state.

See ``local://recruitment-contract.md``. A drive is a ``GuildEvent`` of kind ``recruitment``; this module holds the
guild log rows the drive tracking is built from, and the derived per-recruit rows ``RecruitmentService`` computes
and keeps current (``sidequest_api.domain.recruitment.services``).
"""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime
from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

DRIVE_RECRUIT_STATUSES = ("invited", "counting", "qualified", "disqualified")
DRIVE_RECRUIT_REASONS = ("returning", "own_alt", "left", "low_level", "never_joined")
GUILD_LOG_KINDS = ("invite", "join", "quit", "remove")
PAID_VIA_VALUES = ("site", "addon")


class GuildLogEntry(UUIDAuditBase):
    """One in-game guild event log row, upserted from officers' addon exports (2-hour dedupe on import).

    ``actor`` is the inviter for ``invite``, the member for ``join``/``quit``, or the removing officer for
    ``remove``; ``target`` is the invitee for ``invite`` or the removed member for ``remove``, and ``None`` for
    ``join``/``quit``. ``recorder`` is the addon account that uploaded it. ``promote``/``demote`` are never stored
    (the addon never exports them).
    """

    __tablename__ = "guild_log_entry"
    __table_args__ = (
        Index("ix_guild_log_entry_kind_actor", "kind", "actor"),
        Index("ix_guild_log_entry_kind_target", "kind", "target"),
        {"comment": "In-game guild event log rows (invite/join/quit/remove), from officers' addon exports."},
    )

    kind: Mapped[str] = mapped_column(String(10))
    actor: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text, default=None)
    at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    recorder: Mapped[str] = mapped_column(Text)


class RecruitmentRecruit(UUIDAuditBase):
    """One recruit's qualification state for one drive, upserted by ``RecruitmentService.evaluate``.

    ``recruit_character_id``/``inviter_character_id`` link to ``WowCharacter`` when the name matches exactly one;
    the "own alt" disqualification compares their ``member_id``. ``reward_copper`` snapshots
    ``RECRUIT_REWARD_COPPER`` at qualification time, so a later constant change never alters an amount already
    computed. ``status``/``reason`` are ``DriveRecruitStatus``/``DriveRecruitReason`` values; ``paid_via`` is
    ``PaidVia``.
    """

    __tablename__ = "recruitment_recruit"
    __table_args__ = (
        UniqueConstraint("event_id", "recruit_name", name="uq_recruitment_recruit_event_recruit"),
        {"comment": "One recruit's qualification state for one recruitment drive."},
    )

    event_id: Mapped[UUID] = mapped_column(ForeignKey("guild_event.id", ondelete="CASCADE"), index=True)
    recruit_name: Mapped[str] = mapped_column(Text)
    recruit_character_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("wow_character.id", ondelete="SET NULL"), index=True, default=None
    )
    inviter_name: Mapped[str] = mapped_column(Text, index=True)
    inviter_character_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("wow_character.id", ondelete="SET NULL"), index=True, default=None
    )
    invited_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    joined_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    qualifies_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    status: Mapped[str] = mapped_column(String(15), default="invited")
    reason: Mapped[str | None] = mapped_column(String(15), default=None)
    level: Mapped[int | None] = mapped_column(Integer, default=None)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), index=True, default=None)
    shoutout_posted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    reward_copper: Mapped[int] = mapped_column(Integer, default=10_000)
    """Snapshot of ``sidequest_common.schemas.recruitment.RECRUIT_REWARD_COPPER`` at qualification time."""
    paid_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), index=True, default=None)
    paid_by: Mapped[str | None] = mapped_column(Text, default=None)
    paid_via: Mapped[str | None] = mapped_column(String(10), default=None)
