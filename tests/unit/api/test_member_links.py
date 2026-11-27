from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import BattlenetCharacter, GuildRank, GuildRosterSnapshot, Member, WowCharacter
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


async def test_list_reports_who_is_confirmed_on_the_roster(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """The bot grants the roster role from this flag; without it, approved members never get into the guild."""
    async with db_sessionmaker() as session:
        session.add_all(
            [
                Member(discord_id=111, username="guest", is_guild_member=True),
                Member(
                    discord_id=222, username="approved", is_guild_member=True, roster_confirmed_at=datetime.now(UTC)
                ),
            ]
        )
        await session.commit()

    response = await client.get(LINKS_PATH)
    assert response.status_code == 200
    assert {link["discord_id"]: link["roster_confirmed"] for link in response.json()} == {111: False, 222: True}


async def test_list_empty_when_no_members_signed_in(client: AsyncTestClient) -> None:
    response = await client.get(LINKS_PATH)
    assert response.status_code == 200
    assert response.json() == []


async def test_list_reports_signed_in_false_for_a_discord_only_confirmed_member(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        session.add_all(
            [
                Member(discord_id=111, username="signed-in", is_guild_member=True, last_login_at=datetime.now(UTC)),
                Member(discord_id=222, username="discord-only", is_guild_member=True, last_login_at=None),
            ]
        )
        await session.commit()

    response = await client.get(LINKS_PATH)
    assert response.status_code == 200
    assert {link["discord_id"]: link["signed_in"] for link in response.json()} == {111: True, 222: False}


async def test_list_reports_each_members_in_game_ranks_from_the_battlenet_roster(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """The bot syncs guild rank roles from these. Who holds which rank comes from Battle.net's roster; a character
    linked on the site counts toward ``guild_ranks``, but only one the member's Battle.net account owns counts toward
    ``battlenet_guild_ranks``. A character that left the roster counts toward neither."""

    def character(blizzard_id: int, rank: int | None, *, in_roster: bool = True) -> BattlenetCharacter:
        return BattlenetCharacter(
            slug=f"char-{blizzard_id}",
            blizzard_id=blizzard_id,
            name=f"Char{blizzard_id}",
            surname="Test",
            level=60,
            in_roster=in_roster,
            guild_rank=rank,
        )

    async with db_sessionmaker() as session:
        owner = Member(discord_id=111, username="owner", is_guild_member=True, battlenet_character_ids=[1, 2])
        claimed = Member(discord_id=222, username="claimed", is_guild_member=True)
        gone = Member(discord_id=333, username="gone", is_guild_member=True, battlenet_character_ids=[4])
        session.add_all([owner, claimed, gone])
        await session.flush()
        session.add_all(
            [
                GuildRank(rank_index=0, name="Quest Master"),
                GuildRank(rank_index=3, name="Quest Guide"),
                GuildRank(rank_index=7, name="Adventurer"),
                character(1, 7),
                character(2, 9),  # rank 9 has no name in the rank list: the roster row's name fills it in
                character(3, 0),
                character(4, None, in_roster=False),
                # owner's alt, linked on the site only; claimed's main the same way
                WowCharacter(name="Alt", realm="r", key="alt-r", member_id=owner.id, blizzard_id=5),
                WowCharacter(name="Boss", realm="r", key="boss-r", member_id=claimed.id, blizzard_id=3),
                character(5, 3),
                WowCharacter(name="Snap", realm="r", key="snap-r"),
            ]
        )
        await session.flush()
        snap = (await session.execute(select(WowCharacter).where(WowCharacter.key == "snap-r"))).scalar_one()
        session.add(
            GuildRosterSnapshot(character_id=snap.id, rank="New Arrival", rank_index=9, last_seen_at=datetime.now(UTC))
        )
        await session.commit()

    response = await client.get(LINKS_PATH)
    assert response.status_code == 200
    ranks = {link["discord_id"]: (link["guild_ranks"], link["battlenet_guild_ranks"]) for link in response.json()}
    assert ranks == {
        111: (["Quest Guide", "Adventurer", "New Arrival"], ["Adventurer", "New Arrival"]),
        222: (["Quest Master"], []),
        333: ([], []),
    }
