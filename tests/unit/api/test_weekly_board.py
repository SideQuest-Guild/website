from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sidequest_common.models import GuildEvent
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

WEEKLY_BOARD_PATH = f"/api/guilds/{GUILD_ID}/weekly-board/events"
START = "2026-11-02T00:00:00Z"
END = "2026-11-09T00:00:00Z"


async def test_wrong_guild_id_is_404(client: AsyncTestClient) -> None:
    response = await client.get(f"/api/guilds/{GUILD_ID + 1}/weekly-board/events", params={"start": START, "end": END})
    assert response.status_code == 404


async def test_requires_api_key(client: AsyncTestClient) -> None:
    client.headers.pop("X-API-Key")
    response = await client.get(WEEKLY_BOARD_PATH, params={"start": START, "end": END})
    assert response.status_code == 401


async def test_empty_week_returns_empty_list(client: AsyncTestClient) -> None:
    response = await client.get(WEEKLY_BOARD_PATH, params={"start": START, "end": END})
    assert response.status_code == 200
    assert response.json() == []


async def test_returns_only_events_within_the_range_in_order_with_thread_id(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        session.add_all(
            [
                GuildEvent(
                    kind="raid",
                    title="Molten Core",
                    location="",
                    starts_at=datetime(2026, 11, 5, 19, 0, tzinfo=UTC),
                    status="scheduled",
                    discord_thread_id=555,
                ),
                GuildEvent(
                    kind="dungeon",
                    title="Heroics",
                    location="",
                    starts_at=datetime(2026, 11, 3, 19, 0, tzinfo=UTC),
                    status="scheduled",
                ),
                GuildEvent(
                    kind="social",
                    title="Out of range",
                    location="",
                    starts_at=datetime(2026, 11, 9, 19, 0, tzinfo=UTC),
                    status="scheduled",
                ),
                GuildEvent(
                    kind="raid",
                    title="Cancelled Raid",
                    location="",
                    starts_at=datetime(2026, 11, 4, 19, 0, tzinfo=UTC),
                    status="cancelled",
                ),
            ]
        )
        await session.commit()

    response = await client.get(WEEKLY_BOARD_PATH, params={"start": START, "end": END})
    assert response.status_code == 200
    titles = [event["title"] for event in response.json()]
    assert titles == ["Heroics", "Molten Core"]
    assert response.json()[1]["discord_thread_id"] == 555
    assert response.json()[0]["discord_thread_id"] is None
