"""Scheduled-event lookups and card bookkeeping for the weekly board."""

from typing import TYPE_CHECKING

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import NotFoundException
from sqlalchemy import select

from sidequest_common.models import EventSignup, GuildEvent, Member
from sidequest_common.schemas import BoardSignup, WeeklyBoardEvent, WeeklyBoardMessage

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def board_signups_for(session: AsyncSession, event_ids: Collection[UUID]) -> dict[UUID, list[BoardSignup]]:
    """Every sign-up for each of ``event_ids``, in sign-up order, as the weekly-board cards list them."""
    signups: dict[UUID, list[BoardSignup]] = {event_id: [] for event_id in event_ids}
    if not signups:
        return signups
    statement = (
        select(EventSignup, Member.discord_id)
        .join(Member, EventSignup.member_id == Member.id)
        .where(EventSignup.event_id.in_(signups))
        .order_by(EventSignup.created_at.asc(), EventSignup.id.asc())
    )
    for signup, discord_id in (await session.execute(statement)).all():
        signups[signup.event_id].append(
            BoardSignup(status=signup.status, discord_id=discord_id, wow_class=signup.wow_class, role=signup.role)
        )
    return signups


class WeeklyBoardRepository(SQLAlchemyAsyncRepository[GuildEvent]):
    """Event persistence for the weekly board."""

    model_type = GuildEvent


class WeeklyBoardService(SQLAlchemyAsyncRepositoryService[GuildEvent]):
    """Events scheduled within a given week, for the bot's Monday post, and the card it posted for each."""

    repository_type = WeeklyBoardRepository

    async def list_week_events(self, start: datetime, end: datetime) -> list[WeeklyBoardEvent]:
        """Scheduled (not cancelled/completed) events starting in ``[start, end)``, soonest first, with sign-ups."""
        statement = (
            select(GuildEvent)
            .where(GuildEvent.starts_at >= start, GuildEvent.starts_at < end, GuildEvent.status == "scheduled")
            .order_by(GuildEvent.starts_at.asc())
        )
        session = self.repository.session
        events = list((await session.execute(statement)).scalars().all())
        signups = await board_signups_for(session, [event.id for event in events])
        return [
            WeeklyBoardEvent.model_validate(event).model_copy(update={"signups": signups[event.id]}) for event in events
        ]

    async def set_board_message(self, event_id: UUID, data: WeeklyBoardMessage) -> None:
        """Record ``data`` as ``event_id``'s weekly-board card. 404 if there is no such event."""
        event = await self.get_one_or_none(id=event_id)
        if event is None:
            msg = f"No event {event_id}"
            raise NotFoundException(msg)
        event.discord_board_channel_id = data.channel_id
        event.discord_board_message_id = data.message_id
        await self.update(event, auto_commit=True)
