from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import DiscordLiveStatus
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

LIVE_PATH = f"/api/guilds/{GUILD_ID}/live"
PUBLIC_PATH = "/api/discord/live"


def _report(*, online: int = 12, members: int = 50, voice: list[dict] | None = None) -> dict:
    return {
        "online": online,
        "members": members,
        "voice": voice if voice is not None else [{"name": "Lobby", "count": 2}],
    }


async def test_wrong_guild_id_is_404(client: AsyncTestClient) -> None:
    response = await client.put(f"/api/guilds/{GUILD_ID + 1}/live/", json=_report())
    assert response.status_code == 404


async def test_put_requires_api_key(client: AsyncTestClient) -> None:
    client.headers.pop("X-API-Key")
    response = await client.put(f"{LIVE_PATH}/", json=_report())
    assert response.status_code == 401


async def test_upsert_replaces_previous_report(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    first = await client.put(f"{LIVE_PATH}/", json=_report(online=10, members=40))
    assert first.status_code == 204
    second = await client.put(
        f"{LIVE_PATH}/", json=_report(online=20, members=45, voice=[{"name": "Dungeon-1", "count": 5}])
    )
    assert second.status_code == 204
    async with db_sessionmaker() as session:
        rows = (await session.execute(select(DiscordLiveStatus))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.online == 20
        assert row.members == 45
        assert row.voice == [{"name": "Dungeon-1", "count": 5}]


async def test_public_get_returns_the_report(client: AsyncTestClient) -> None:
    await client.put(f"{LIVE_PATH}/", json=_report(online=7, members=30, voice=[{"name": "Raid VC", "count": 3}]))
    response = await client.get(PUBLIC_PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["online"] == 7
    assert body["members"] == 30
    assert body["voice"] == [{"name": "Raid VC", "count": 3}]
    assert body["reported_at"] is not None


async def test_public_get_with_no_row_returns_empty_counts(client: AsyncTestClient) -> None:
    response = await client.get(PUBLIC_PATH)
    assert response.status_code == 200
    body = response.json()
    assert body == {"online": None, "members": None, "voice": [], "reported_at": None}


async def test_public_get_with_stale_report_returns_empty_counts(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    stale_at = datetime.now(UTC) - timedelta(seconds=181)
    async with db_sessionmaker() as session:
        session.add(
            DiscordLiveStatus(
                guild_id=GUILD_ID,
                online=5,
                members=20,
                voice=[{"name": "Lobby", "count": 1}],
                reported_at=stale_at,
            )
        )
        await session.commit()

    response = await client.get(PUBLIC_PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["online"] is None
    assert body["members"] is None
    assert body["voice"] == []
    assert body["reported_at"] is not None
