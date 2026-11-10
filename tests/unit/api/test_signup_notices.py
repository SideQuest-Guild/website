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
    signed_in: bool = True,
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
            last_login_at=datetime.now(UTC) if signed_in else None,
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


async def test_pending_excludes_a_member_who_has_never_signed_in(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(db_sessionmaker, discord_id=8014, username="discord-only", signed_in=False)
    response = await client.get(NOTICES_PATH)
    assert response.status_code == 200
    pending_ids = {row["member_id"] for row in response.json()["pending"]}
    assert member_id not in pending_ids


async def test_pending_includes_the_member_once_they_sign_in(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(db_sessionmaker, discord_id=8015, username="discord-only", signed_in=False)
    async with db_sessionmaker() as session:
        member = await session.get(Member, member_id)
        assert member is not None
        member.last_login_at = datetime.now(UTC)
        await session.commit()

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


async def test_confirm_from_notice_unknown_actor_is_403(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(db_sessionmaker, discord_id=8006, username="target")
    response = await client.put(
        f"{NOTICES_PATH}/{member_id}/roster-confirmation",
        json={"actor_discord_id": "999999999", "actor_name": "Nobody"},
    )
    assert response.status_code == 403


async def test_confirm_from_notice_non_gm_actor_is_403(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(db_sessionmaker, discord_id=8007, username="target")
    await _seed_member(db_sessionmaker, discord_id=8008, username="rando", roles=[])
    response = await client.put(
        f"{NOTICES_PATH}/{member_id}/roster-confirmation",
        json={"actor_discord_id": "8008", "actor_name": "Rando"},
    )
    assert response.status_code == 403


async def test_confirm_from_notice_unknown_member_is_404(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=8009, username="gm", roles=[GM_ROLE_ID])
    response = await client.put(
        f"{NOTICES_PATH}/999999999/roster-confirmation",
        json={"actor_discord_id": "8009", "actor_name": "GM"},
    )
    assert response.status_code == 404


async def test_gm_confirms_notice_member_not_self_and_records_audit(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(db_sessionmaker, discord_id=8010, username="target")
    gm_id = await _seed_member(db_sessionmaker, discord_id=8011, username="gm-clicker", roles=[GM_ROLE_ID])

    response = await client.put(
        f"{NOTICES_PATH}/{member_id}/roster-confirmation",
        json={"actor_discord_id": "8011", "actor_name": "GM Clicker"},
    )
    assert response.status_code == 200
    assert response.json()["roster_confirmed"] is True

    async with db_sessionmaker() as session:
        target = await session.get(Member, member_id)
        gm = await session.get(Member, gm_id)
        assert target is not None
        assert target.roster_confirmed_at is not None
        assert gm is not None
        assert gm.roster_confirmed_at is None
        audit = (await session.scalars(select(OfficerAudit).where(OfficerAudit.action == "roster.confirm"))).one()
        assert audit.subject_id == str(member_id)
        assert audit.actor_name == "gm-clicker"


async def test_gm_unconfirms_from_notice_and_records_audit(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _seed_member(db_sessionmaker, discord_id=8012, username="target", confirmed=True)
    await _seed_member(db_sessionmaker, discord_id=8013, username="gm-clicker", roles=[GM_ROLE_ID])

    response = await client.request(
        "DELETE",
        f"{NOTICES_PATH}/{member_id}/roster-confirmation",
        json={"actor_discord_id": "8013", "actor_name": "GM Clicker"},
    )
    assert response.status_code == 200
    assert response.json()["roster_confirmed"] is False

    async with db_sessionmaker() as session:
        audit = (await session.scalars(select(OfficerAudit).where(OfficerAudit.action == "roster.remove"))).one()
        assert audit.actor_name == "gm-clicker"


async def test_confirm_discord_member_creates_member_and_confirms(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=8020, username="gm-clicker", roles=[GM_ROLE_ID])

    response = await client.put(
        f"/api/guilds/{GUILD_ID}/discord-members/8021/roster-confirmation",
        json={
            "actor_discord_id": "8020",
            "actor_name": "GM Clicker",
            "profile": {
                "discord_id": 8021,
                "username": "never-signed-in",
                "global_name": None,
                "guild_nick": "Newbie",
                "avatar_hash": None,
                "roles": [],
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["roster_confirmed"] is True

    async with db_sessionmaker() as session:
        created = (await session.scalars(select(Member).where(Member.discord_id == 8021))).one()
        assert created.last_login_at is None
        assert created.is_guild_member is True
        assert created.roster_confirmed_via == "officer"
        assert created.roster_removed_at is None
        audit = (
            await session.scalars(
                select(OfficerAudit).where(
                    OfficerAudit.action == "roster.confirm", OfficerAudit.subject_id == str(created.id)
                )
            )
        ).one()
        assert audit.actor_name == "gm-clicker"


async def test_confirm_discord_member_refreshes_an_existing_member(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=8022, username="gm-clicker", roles=[GM_ROLE_ID])
    member_id = await _seed_member(db_sessionmaker, discord_id=8023, username="old-name")

    response = await client.put(
        f"/api/guilds/{GUILD_ID}/discord-members/8023/roster-confirmation",
        json={
            "actor_discord_id": "8022",
            "actor_name": "GM Clicker",
            "profile": {
                "discord_id": 8023,
                "username": "new-name",
                "global_name": "New Name",
                "guild_nick": None,
                "avatar_hash": "abc123",
                "roles": [GM_ROLE_ID],
            },
        },
    )
    assert response.status_code == 200

    async with db_sessionmaker() as session:
        refreshed = await session.get(Member, member_id)
        assert refreshed is not None
        assert refreshed.username == "new-name"
        assert refreshed.global_name == "New Name"
        assert refreshed.avatar_hash == "abc123"
        assert refreshed.roster_confirmed_at is not None


async def test_confirm_discord_member_non_gm_actor_is_403(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=8024, username="rando")

    response = await client.put(
        f"/api/guilds/{GUILD_ID}/discord-members/8025/roster-confirmation",
        json={
            "actor_discord_id": "8024",
            "actor_name": "Rando",
            "profile": {
                "discord_id": 8025,
                "username": "target",
                "global_name": None,
                "guild_nick": None,
                "avatar_hash": None,
                "roles": [],
            },
        },
    )
    assert response.status_code == 403


async def test_confirm_discord_member_profile_mismatch_is_400(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=8026, username="gm-clicker", roles=[GM_ROLE_ID])

    response = await client.put(
        f"/api/guilds/{GUILD_ID}/discord-members/8027/roster-confirmation",
        json={
            "actor_discord_id": "8026",
            "actor_name": "GM Clicker",
            "profile": {
                "discord_id": 9999,
                "username": "mismatched",
                "global_name": None,
                "guild_nick": None,
                "avatar_hash": None,
                "roles": [],
            },
        },
    )
    assert response.status_code == 400


async def test_confirm_discord_member_wrong_guild_is_404(client: AsyncTestClient) -> None:
    response = await client.put(
        "/api/guilds/999999/discord-members/8028/roster-confirmation",
        json={
            "actor_discord_id": "1",
            "actor_name": "GM",
            "profile": {
                "discord_id": 8028,
                "username": "target",
                "global_name": None,
                "guild_nick": None,
                "avatar_hash": None,
                "roles": [],
            },
        },
    )
    assert response.status_code == 404
