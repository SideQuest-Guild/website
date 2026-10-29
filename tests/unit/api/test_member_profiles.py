from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import Member
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PROFILES_PATH = f"/api/guilds/{GUILD_ID}/member-profiles"


def _body(*, profiles: list[dict] | None = None, departed_ids: list[int] | None = None) -> dict:
    return {"profiles": profiles or [], "departed_ids": departed_ids or []}


def _profile(discord_id: int, **overrides: object) -> dict:
    base: dict[str, object] = {
        "discord_id": discord_id,
        "username": "hailcaesar4288",
        "global_name": "HailCaesar",
        "guild_nick": None,
        "avatar_hash": "abc123",
        "roles": [111, 222],
    }
    base.update(overrides)
    return base


async def _get_member(session: AsyncSession, discord_id: int) -> Member:
    return (await session.execute(select(Member).where(Member.discord_id == discord_id))).scalar_one()


async def test_wrong_guild_id_is_404(client: AsyncTestClient) -> None:
    response = await client.put(f"/api/guilds/{GUILD_ID + 1}/member-profiles/", json=_body())
    assert response.status_code == 404


async def test_requires_api_key(client: AsyncTestClient) -> None:
    client.headers.pop("X-API-Key")
    response = await client.put(f"{PROFILES_PATH}/", json=_body())
    assert response.status_code == 401


async def test_updates_an_existing_member(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        session.add(
            Member(
                discord_id=1,
                username="old-username",
                global_name="Old Name",
                guild_nick="Old Nick",
                avatar_hash="old-hash",
                roles=[999],
                is_guild_member=True,
            )
        )
        await session.commit()
    response = await client.put(f"{PROFILES_PATH}/", json=_body(profiles=[_profile(1, guild_nick="Trey", roles=[111])]))
    assert response.status_code == 204

    async with db_sessionmaker() as session:
        member = await _get_member(session, 1)
        assert member.username == "hailcaesar4288"
        assert member.global_name == "HailCaesar"
        assert member.guild_nick == "Trey"
        assert member.avatar_hash == "abc123"
        assert member.roles == [111]
        assert member.is_guild_member is True


async def test_ignores_unknown_discord_ids(client: AsyncTestClient) -> None:
    response = await client.put(f"{PROFILES_PATH}/", json=_body(profiles=[_profile(999999)], departed_ids=[888888]))
    assert response.status_code == 204


async def test_departed_clears_nick_and_roles_and_marks_not_a_guild_member(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        session.add(
            Member(discord_id=2, username="left-member", guild_nick="Nick", roles=[111, 222], is_guild_member=True)
        )
        await session.commit()

    response = await client.put(f"{PROFILES_PATH}/", json=_body(departed_ids=[2]))
    assert response.status_code == 204

    async with db_sessionmaker() as session:
        member = await _get_member(session, 2)
        assert member.is_guild_member is False
        assert member.guild_nick is None
        assert member.roles == []


async def test_does_not_touch_last_login_battlenet_or_roster_confirmation(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    last_login = datetime(2025, 1, 1, tzinfo=UTC)
    roster_confirmed = datetime(2025, 2, 1, tzinfo=UTC)
    async with db_sessionmaker() as session:
        session.add(
            Member(
                discord_id=3,
                username="old-username",
                is_guild_member=True,
                last_login_at=last_login,
                battlenet_id=555,
                battletag="Tester#1111",
                roster_confirmed_at=roster_confirmed,
            )
        )
        await session.commit()

    response = await client.put(f"{PROFILES_PATH}/", json=_body(profiles=[_profile(3)]))
    assert response.status_code == 204

    async with db_sessionmaker() as session:
        member = await _get_member(session, 3)
        assert member.last_login_at == last_login
        assert member.battlenet_id == 555
        assert member.battletag == "Tester#1111"
        assert member.roster_confirmed_at == roster_confirmed
        assert member.username == "hailcaesar4288"
