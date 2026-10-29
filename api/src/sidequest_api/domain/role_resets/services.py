"""Discord role-reset outbox persistence: list pending resets for the bot, and ack once applied."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import NotFoundException
from sqlalchemy import delete, select

from sidequest_common.models import MemberRoleReset

if TYPE_CHECKING:
    from uuid import UUID

ROLE_RESET_LIMIT = 50
ROLE_RESET_RETENTION = timedelta(days=7)


class MemberRoleResetsRepository(SQLAlchemyAsyncRepository[MemberRoleReset]):
    """MemberRoleReset persistence."""

    model_type = MemberRoleReset


class MemberRoleResetsService(SQLAlchemyAsyncRepositoryService[MemberRoleReset]):
    """Lists pending Discord role resets for the bot, and acks them once the bot has applied them."""

    repository_type = MemberRoleResetsRepository

    async def list_pending(self, limit: int = ROLE_RESET_LIMIT) -> list[MemberRoleReset]:
        """Unacked resets, oldest first, capped at ``limit``.

        Drops unacked rows older than ``ROLE_RESET_RETENTION`` first: a member who left the guild before the bot
        could act is never going to be acked, and the row would otherwise sit in the outbox forever.
        """
        session = self.repository.session
        cutoff = datetime.now(UTC) - ROLE_RESET_RETENTION
        await session.execute(
            delete(MemberRoleReset).where(MemberRoleReset.done_at.is_(None), MemberRoleReset.requested_at < cutoff)
        )
        await session.commit()
        statement = (
            select(MemberRoleReset)
            .where(MemberRoleReset.done_at.is_(None))
            .order_by(MemberRoleReset.requested_at)
            .limit(limit)
        )
        return list((await session.execute(statement)).scalars())

    async def get_for_bot_action(self, reset_id: UUID) -> MemberRoleReset:
        """``reset_id``'s row. Raises ``NotFoundException`` if no such reset exists."""
        reset = await self.get_one_or_none(id=reset_id)
        if reset is None:
            msg = f"No role reset {reset_id}"
            raise NotFoundException(msg)
        return reset

    async def ack(self, reset: MemberRoleReset) -> MemberRoleReset:
        """Record that the bot has stripped ``reset``'s member's roles (or found them no longer in the guild)."""
        reset.done_at = datetime.now(UTC)
        return await self.update(reset, auto_commit=True)
