from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import Member, OfficerAudit
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOTICES_PATH = f"/api/guilds/{GUILD_ID}/signup-notices"
GM_ROLE_ID = 1564678042381586532


async def _seed_member(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    discord_id: int,
    username: str = "newbie",
    roles: list[int] | None = None,
    posted: bool = False,
    confirmed: bool = False,
    message_posted: bool = False,
) -> int:
    async with db_sessionmaker() as session:
        member = Member(
            discord_id=discord_id,
            username=username,
            roles=roles or [],
            officer_notice_posted_at=datetime.now(UTC) if posted else None,
            officer_notice_channel_id=555 if message_posted else None,
            officer_notice_message_id=666 if message_posted else None,
            roster_confirmed_at=datetime.now(UTC) if confirmed else None,
        )
        session.add(member)
        await session.commit()
        await session.refresh(member)
        return member.id


async def test_wrong_guild_404(client: AsyncTestClient) -> None:
    response = await client.get("/api/guilds/999999/signup-notices")
    assert response.status_code == 404


async def test_pending_includes_new_unposted_member(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(db_sessionmaker, discord_id=8001, username="freshling")
    response = await client.get(NOTICES_PATH)
    assert response.status_code == 200
    pending_ids = {row["member_id"] for row in response.json()["pending"]}
    assert member_id in pending_ids


async def test_pending_excludes_already_posted_member(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(db_sessionmaker, discord_id=8002, username="known", posted=True)
    response = await client.get(NOTICES_PATH)
    pending_ids = {row["member_id"] for row in response.json()["pending"]}
    assert member_id not in pending_ids


async def test_ack_removes_member_from_pending(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(db_sessionmaker, discord_id=8003, username="acked")
    ack = await client.post(f"{NOTICES_PATH}/{member_id}/ack", json={"channel_id": 111, "message_id": 222})
    assert ack.status_code == 204
    response = await client.get(NOTICES_PATH)
    pending_ids = {row["member_id"] for row in response.json()["pending"]}
    assert member_id not in pending_ids


async def test_resolved_lists_confirmed_member_with_posted_message(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(
        db_sessionmaker, discord_id=8004, username="confirmed-on-site", posted=True, message_posted=True, confirmed=True
    )
    response = await client.get(NOTICES_PATH)
    resolved_ids = {row["member_id"] for row in response.json()["resolved"]}
    assert member_id in resolved_ids


async def test_ack_resolves_a_confirmed_member(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(
        db_sessionmaker, discord_id=8005, username="confirmed-ack", posted=True, message_posted=True, confirmed=True
    )
    ack = await client.post(f"{NOTICES_PATH}/{member_id}/ack", json={"channel_id": 555, "message_id": 666})
    assert ack.status_code == 204
    response = await client.get(NOTICES_PATH)
    resolved_ids = {row["member_id"] for row in response.json()["resolved"]}
    assert member_id not in resolved_ids


async def test_confirm_by_discord_unknown_actor_is_403(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=8006, username="target")
    response = await client.put(
        f"/api/guilds/{GUILD_ID}/members/by-discord/8006/roster-confirmation",
        json={"actor_discord_id": "999999999", "actor_name": "Nobody"},
    )
    assert response.status_code == 403


async def test_confirm_by_discord_non_gm_actor_is_403(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=8007, username="target")
    await _seed_member(db_sessionmaker, discord_id=8008, username="rando", roles=[])
    response = await client.put(
        f"/api/guilds/{GUILD_ID}/members/by-discord/8007/roster-confirmation",
        json={"actor_discord_id": "8008", "actor_name": "Rando"},
    )
    assert response.status_code == 403


async def test_confirm_by_discord_unknown_member_is_404(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=8009, username="gm", roles=[GM_ROLE_ID])
    response = await client.put(
        f"/api/guilds/{GUILD_ID}/members/by-discord/999999999/roster-confirmation",
        json={"actor_discord_id": "8009", "actor_name": "GM"},
    )
    assert response.status_code == 404


async def test_gm_confirms_by_discord_and_records_audit(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(db_sessionmaker, discord_id=8010, username="target")
    await _seed_member(db_sessionmaker, discord_id=8011, username="gm-clicker", roles=[GM_ROLE_ID])

    response = await client.put(
        f"/api/guilds/{GUILD_ID}/members/by-discord/8010/roster-confirmation",
        json={"actor_discord_id": "8011", "actor_name": "GM Clicker"},
    )
    assert response.status_code == 200
    assert response.json()["roster_confirmed"] is True

    async with db_sessionmaker() as session:
        audit = (await session.scalars(select(OfficerAudit).where(OfficerAudit.action == "roster.confirm"))).one()
        assert audit.subject_id == str(member_id)
        assert audit.actor_name == "gm-clicker"


async def test_gm_unconfirms_by_discord_and_records_audit(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=8012, username="target", confirmed=True)
    await _seed_member(db_sessionmaker, discord_id=8013, username="gm-clicker", roles=[GM_ROLE_ID])

    response = await client.request(
        "DELETE",
        f"/api/guilds/{GUILD_ID}/members/by-discord/8012/roster-confirmation",
        json={"actor_discord_id": "8013", "actor_name": "GM Clicker"},
    )
    assert response.status_code == 200
    assert response.json()["roster_confirmed"] is False

    async with db_sessionmaker() as session:
        audit = (await session.scalars(select(OfficerAudit).where(OfficerAudit.action == "roster.remove"))).one()
        assert audit.actor_name == "gm-clicker"
