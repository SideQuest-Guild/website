"""Member away date ranges: CRUD, pruning past ranges, and the "away today"/"away on a date" queries."""

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import NotFoundException
from sqlalchemy import delete, select

from sidequest_common.models import Member, MemberAwayRange

if TYPE_CHECKING:
    from uuid import UUID

    from sidequest_common.schemas import AwayRangeIn

GUILD_TZ = ZoneInfo("America/Chicago")
"""US guild: an away range covers a calendar day in Central time, matching the bot's presence clock."""


def today_chicago(now: datetime | None = None) -> date:
    """Today's date in America/Chicago, for comparing against stored (date-only) away ranges."""
    return (now or datetime.now(UTC)).astimezone(GUILD_TZ).date()


class AwayRepository(SQLAlchemyAsyncRepository[MemberAwayRange]):
    """MemberAwayRange persistence."""

    model_type = MemberAwayRange


class AwayService(SQLAlchemyAsyncRepositoryService[MemberAwayRange]):
    """A member's away ranges: add/remove, with past ranges pruned on every read."""

    repository_type = AwayRepository

    async def list_for_member(self, member: Member, *, today: date | None = None) -> list[MemberAwayRange]:
        """``member``'s away ranges, soonest first. Ranges that ended before today are deleted first."""
        today = today or today_chicago()
        session = self.repository.session
        await session.execute(
            delete(MemberAwayRange).where(MemberAwayRange.member_id == member.id, MemberAwayRange.end_date < today)
        )
        await session.commit()
        statement = (
            select(MemberAwayRange).where(MemberAwayRange.member_id == member.id).order_by(MemberAwayRange.start_date)
        )
        return list((await session.execute(statement)).scalars())

    async def add_range(self, member: Member, data: AwayRangeIn) -> MemberAwayRange:
        """Record a new away range for ``member``."""
        away_range = MemberAwayRange(
            member_id=member.id, start_date=data.start_date, end_date=data.end_date, note=data.note
        )
        return await self.create(away_range, auto_commit=True)

    async def delete_for_member(self, member: Member, range_id: UUID) -> None:
        """Remove one of ``member``'s own away ranges. 404 if it doesn't exist or belongs to someone else."""
        away_range = await self.get_one_or_none(id=range_id, member_id=member.id)
        if away_range is None:
            msg = f"No away range {range_id}"
            raise NotFoundException(msg)
        await self.delete(away_range.id, auto_commit=True)

    async def discord_ids_away_now(self, *, today: date | None = None) -> list[int]:
        """Discord ids of every member (signed in or not) whose away range covers today in Chicago."""
        today = today or today_chicago()
        session = self.repository.session
        statement = (
            select(Member.discord_id)
            .join(MemberAwayRange, MemberAwayRange.member_id == Member.id)
            .where(MemberAwayRange.start_date <= today, MemberAwayRange.end_date >= today)
            .distinct()
        )
        return list((await session.execute(statement)).scalars())

    async def members_away_on(self, on_date: date) -> list[Member]:
        """Members whose away range covers ``on_date`` (used to flag an event's roster)."""
        session = self.repository.session
        statement = (
            select(Member)
            .join(MemberAwayRange, MemberAwayRange.member_id == Member.id)
            .where(MemberAwayRange.start_date <= on_date, MemberAwayRange.end_date >= on_date)
            .distinct()
        )
        return list((await session.execute(statement)).scalars())
