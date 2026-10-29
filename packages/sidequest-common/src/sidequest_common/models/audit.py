"""Officer/GM console action audit trail."""

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class OfficerAudit(UUIDAuditBase):
    """One officer/GM-performed change, recorded in the same request as the change itself.

    Bot/Discord-originated changes are never audited here (no officer/GM actor). ``actor_name`` is a snapshot of
    the actor's display name at the time, so the row still reads sensibly after ``actor_member_id`` is nulled
    (kept, not deleted) when the actor's account is later deleted.
    """

    __tablename__ = "officer_audit"
    __table_args__ = {"comment": "Officer/GM console action audit trail."}

    actor_member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("member.id", ondelete="SET NULL"), index=True, default=None
    )
    actor_name: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(40))
    subject_type: Mapped[str] = mapped_column(String(20))
    subject_id: Mapped[str | None] = mapped_column(String(64), default=None)
    summary: Mapped[str] = mapped_column(String(300))
