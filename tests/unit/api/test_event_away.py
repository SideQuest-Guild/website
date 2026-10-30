"""``EventDetail.away``: members away on an event's start date (America/Chicago), ``None`` for anonymous viewers."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import select

from sidequest_common.models import GuildEvent, Member, MemberAwayRange
from tests.unit.api.conftest import login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_CHICAGO = ZoneInfo("America/Chicago")


async def _seed_event_at(db_sessionmaker: async_sessionmaker[AsyncSession], starts_at: datetime) -> str:
    async with db_sessionmaker() as session:
        event = GuildEvent(kind="raid", title="Molten Core", location="MC", starts_at=starts_at, size=40)
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return str(event.id)


async def test_away_is_none_for_anonymous_viewers(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    starts_at = datetime.now(UTC) + timedelta(days=1)
    event_id = await _seed_event_at(db_sessionmaker, starts_at)
    response = await member_client.get(f"/api/events/{event_id}")
    assert response.status_code == 200
    assert response.json()["away"] is None


async def test_away_lists_members_whose_range_covers_the_event_start_date(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    # Pin the event's start comfortably inside one Chicago calendar day, away from UTC-day boundaries.
    local_start = datetime(2026, 12, 10, 20, 0, tzinfo=_CHICAGO)
    event_id = await _seed_event_at(db_sessionmaker, local_start.astimezone(UTC))

    await login_as(member_client, discord_state, discord_id=8001, username="away-raider")
    async with db_sessionmaker() as session:
        member = (await session.execute(select(Member).where(Member.discord_id == 8001))).scalar_one()
        session.add(
            MemberAwayRange(
                member_id=member.id,
                start_date=local_start.date() - timedelta(days=1),
                end_date=local_start.date() + timedelta(days=1),
            )
        )

        other_member = Member(discord_id=8002, username="not-away")
        session.add(other_member)
        await session.flush()
        session.add(
            MemberAwayRange(
                member_id=other_member.id,
                start_date=local_start.date() + timedelta(days=10),
                end_date=local_start.date() + timedelta(days=12),
            )
        )
        await session.commit()

    response = await member_client.get(f"/api/events/{event_id}")
    assert response.status_code == 200
    away = response.json()["away"]
    assert away is not None
    assert [m["display_name"] for m in away] == ["away-raider"]
