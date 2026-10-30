"""Scheduled-event lookups for the weekly board."""

from typing import TYPE_CHECKING

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from sqlalchemy import select

from sidequest_common.models import GuildEvent

if TYPE_CHECKING:
    from datetime import datetime


class WeeklyBoardRepository(SQLAlchemyAsyncRepository[GuildEvent]):
    """Event persistence for the weekly board."""

    model_type = GuildEvent


class WeeklyBoardService(SQLAlchemyAsyncRepositoryService[GuildEvent]):
    """Events scheduled within a given week, for the bot's Monday post."""

    repository_type = WeeklyBoardRepository

    async def list_week_events(self, start: datetime, end: datetime) -> list[GuildEvent]:
        """Scheduled (not cancelled/completed) events starting in ``[start, end)``, soonest first."""
        statement = (
            select(GuildEvent)
            .where(GuildEvent.starts_at >= start, GuildEvent.starts_at < end, GuildEvent.status == "scheduled")
            .order_by(GuildEvent.starts_at.asc())
        )
        session = self.repository.session
        return list((await session.execute(statement)).scalars().all())
