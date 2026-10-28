from typing import TYPE_CHECKING

from sidequest_common.models import Member
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

LINKS_PATH = f"/api/guilds/{GUILD_ID}/member-links"


async def test_wrong_guild_id_is_404(client: AsyncTestClient) -> None:
    response = await client.get(f"/api/guilds/{GUILD_ID + 1}/member-links")
    assert response.status_code == 404


async def test_requires_api_key(client: AsyncTestClient) -> None:
    client.headers.pop("X-API-Key")
    response = await client.get(LINKS_PATH)
    assert response.status_code == 401


async def test_list_includes_signed_in_members_with_correct_battlenet_linked(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        session.add_all(
            [
                Member(discord_id=111, username="linked-only", is_guild_member=True),
                Member(
                    discord_id=222,
                    username="battlenet-too",
                    is_guild_member=True,
                    battlenet_id=999,
                    battletag="Tester#1111",
                ),
            ]
        )
        await session.commit()

    response = await client.get(LINKS_PATH)
    assert response.status_code == 200
    links = {link["discord_id"]: link["battlenet_linked"] for link in response.json()}
    assert links == {111: False, 222: True}


async def test_list_empty_when_no_members_signed_in(client: AsyncTestClient) -> None:
    response = await client.get(LINKS_PATH)
    assert response.status_code == 200
    assert response.json() == []
