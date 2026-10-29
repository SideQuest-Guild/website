"""``/api/guilds/{guild_id}/role-resets``: Discord role resets owed after a site account deletion."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from sidequest_api.domain.role_resets.services import ROLE_RESET_RETENTION
from sidequest_common.models import MemberRoleReset
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

RESETS_PATH = f"/api/guilds/{GUILD_ID}/role-resets"


async def _seed_reset(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    discord_id: int,
    requested_at: datetime | None = None,
    done_at: datetime | None = None,
) -> str:
    async with db_sessionmaker() as session:
        reset = MemberRoleReset(discord_id=discord_id, requested_at=requested_at or datetime.now(UTC), done_at=done_at)
        session.add(reset)
        await session.commit()
        await session.refresh(reset)
        return str(reset.id)


async def test_wrong_guild_404_on_list(client: AsyncTestClient) -> None:
    response = await client.get("/api/guilds/999999/role-resets")
    assert response.status_code == 404


async def test_wrong_guild_404_on_ack(client: AsyncTestClient) -> None:
    response = await client.post(f"/api/guilds/999999/role-resets/{uuid4()}/ack")
    assert response.status_code == 404


async def test_requires_api_key(client: AsyncTestClient) -> None:
    client.headers.pop("X-API-Key")
    response = await client.get(RESETS_PATH)
    assert response.status_code == 401


async def test_list_empty_when_no_resets(client: AsyncTestClient) -> None:
    response = await client.get(RESETS_PATH)
    assert response.status_code == 200
    assert response.json() == []


async def test_list_includes_pending_reset(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_reset(db_sessionmaker, discord_id=7001)
    response = await client.get(RESETS_PATH)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["discord_id"] == 7001


async def test_list_excludes_already_acked_reset(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_reset(db_sessionmaker, discord_id=7002, done_at=datetime.now(UTC))
    response = await client.get(RESETS_PATH)
    assert response.status_code == 200
    assert response.json() == []


async def test_list_is_oldest_first(client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    now = datetime.now(UTC)
    await _seed_reset(db_sessionmaker, discord_id=7003, requested_at=now)
    await _seed_reset(db_sessionmaker, discord_id=7004, requested_at=now - timedelta(minutes=5))
    response = await client.get(RESETS_PATH)
    assert [reset["discord_id"] for reset in response.json()] == [7004, 7003]


async def test_list_drops_stale_unacked_rows(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    stale_id = await _seed_reset(
        db_sessionmaker, discord_id=7005, requested_at=datetime.now(UTC) - ROLE_RESET_RETENTION - timedelta(days=1)
    )
    response = await client.get(RESETS_PATH)
    assert response.status_code == 200
    assert response.json() == []

    ack_response = await client.post(f"/api/guilds/{GUILD_ID}/role-resets/{stale_id}/ack")
    assert ack_response.status_code == 404


async def test_ack_unknown_reset_is_404(client: AsyncTestClient) -> None:
    response = await client.post(f"{RESETS_PATH}/{uuid4()}/ack")
    assert response.status_code == 404


async def test_ack_removes_reset_from_pending_listing(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    reset_id = await _seed_reset(db_sessionmaker, discord_id=7006)

    response = await client.post(f"{RESETS_PATH}/{reset_id}/ack")
    assert response.status_code == 204

    listing = await client.get(RESETS_PATH)
    assert listing.json() == []
