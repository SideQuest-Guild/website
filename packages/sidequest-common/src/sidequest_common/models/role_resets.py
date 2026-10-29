"""Discord role-reset outbox: a site account was deleted and must be stripped of every manageable Discord role."""

from datetime import UTC, datetime  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column


class MemberRoleReset(UUIDAuditBase):
    """One Discord user who deleted their site account and still needs their Discord roles stripped.

    Written by ``MembersService.delete_account`` in the same transaction as the account deletion, so the outbox
    row survives even though the ``Member`` row it's about is gone. The bot's ``link_roles`` plugin removes every
    role it can manage from ``discord_id`` (keeping ``@everyone``, managed/integration roles, and anything at or
    above its own top role, which Discord would reject anyway) and immediately re-grants the gate role, since the
    member is now unlinked; it then acks via ``POST .../role-resets/{id}/ack``, which sets ``done_at``. A member
    no longer in the guild is acked as done without any role changes. ``requested_at`` orders the outbox
    oldest-first; rows that go unacked past the API's retention window (e.g. the member left before the bot could
    act) are dropped by the listing route rather than sitting forever.
    """

    __tablename__ = "member_role_reset"
    __table_args__ = {"comment": "Outbox: Discord role resets owed after a site account deletion."}

    discord_id: Mapped[int] = mapped_column(BigInteger, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), default=lambda: datetime.now(UTC))
    done_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
