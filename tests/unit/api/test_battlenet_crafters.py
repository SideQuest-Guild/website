"""The roster sync fills the crafter directory from Battle.net's character professions for roster members the
addon has never scanned, translating Battle.net's recipe ids through ``battlenet_recipe_map.json``.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select
from wow import AsyncClient

from sidequest_api.domain.characters.services import CharactersService
from sidequest_api.domain.guild_hub.services import GuildHubService
from sidequest_common.models import CharacterProfession, WowCharacter
from tests.unit.api.fake_battlenet import TERRORSKULL, battlenet, forget_battlenet_state, roster_member, transport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name

# Terrorskull Gloomstep's recorded profile, shared by every character profile the fake serves (renamed per slug).
TERRORSKULL_LAST_LOGIN_AT = datetime.fromtimestamp(1793869523, tz=UTC)


def _wow_character_statement(key: str):
    return select(WowCharacter).where(WowCharacter.key == key)


def _character_profession_statement(key: str, profession: str):
    return (
        select(CharacterProfession)
        .join(WowCharacter, WowCharacter.id == CharacterProfession.character_id)
        .where(WowCharacter.key == key, CharacterProfession.profession == profession)
    )


def _professions_document(
    *,
    character_id: int,
    slug: str,
    name: str,
    surname: str,
    profession_id: int,
    profession_name: str,
    skill: int,
    max_skill: int,
    recipes: list[tuple[int, str]],
) -> dict:
    """A Battle.net ``/professions`` document body with one primary profession and its known recipes."""
    link = {"href": "https://us.api.blizzard.com/x"}
    return {
        "_links": {"self": link},
        "character": {"key": link, "id": character_id, "name": name, "surname": surname, "slug": slug},
        "primaries": [
            {
                "profession": {"key": link, "id": profession_id, "name": profession_name},
                "tiers": [
                    {
                        "tier": {"id": profession_id, "name": profession_name},
                        "skill_points": skill,
                        "max_skill_points": max_skill,
                        "known_recipes": [
                            {"key": link, "id": recipe_id, "name": recipe_name} for recipe_id, recipe_name in recipes
                        ],
                    }
                ],
            }
        ],
        "secondaries": [],
    }


async def test_roster_member_without_the_addon_becomes_a_crafter_from_battlenet(
    db_sessionmaker: async_sessionmaker[AsyncSession], battlenet: dict
) -> None:
    """A roster character the addon has never scanned gets a ``WowCharacter``/``CharacterProfession`` row from
    Battle.net's published professions, with its known recipes translated to the game's own recipe ids."""
    battlenet["roster"].append(roster_member("Terrorskull", "Gloomstep", rank=2, level=12))

    async with httpx.AsyncClient(transport=transport(battlenet)) as http:
        game_data = AsyncClient("bnet-id", "bnet-secret", http_client=http)
        async with db_sessionmaker() as session:
            await CharactersService(session).sync_roster(game_data)

    async with db_sessionmaker() as session:
        character = (await session.execute(_wow_character_statement(TERRORSKULL))).scalar_one()
        assert character.source == "import"
        assert character.blizzard_id is not None
        result = await GuildHubService(session).get_crafters(
            q="Handstitched Leather Boots", profession=None, game_data=None
        )
    assert len(result.results) == 1
    recipe = result.results[0]
    assert recipe.recipe_name == "Handstitched Leather Boots"
    assert recipe.recipe_id == 2149  # the game's spell id, translated from Battle.net's SkillLineAbility id 1353
    assert recipe.item_id == 2302
    assert recipe.crafters[0].character == TERRORSKULL


async def test_a_newer_addon_scan_is_not_overwritten_by_battlenet(
    db_sessionmaker: async_sessionmaker[AsyncSession], battlenet: dict
) -> None:
    """An addon scan newer than Battle.net's last-logout data for the same character/profession stays as is."""
    battlenet["roster"].append(roster_member("Terrorskull", "Gloomstep", rank=2, level=12))
    newer = TERRORSKULL_LAST_LOGIN_AT.replace(year=TERRORSKULL_LAST_LOGIN_AT.year + 1)
    async with db_sessionmaker() as session:
        character = WowCharacter(name="Terrorskull", realm="", key=TERRORSKULL, source="import")
        session.add(character)
        await session.flush()
        session.add(
            CharacterProfession(
                character_id=character.id, profession="Leatherworking", skill=999, max_skill=999, scanned_at=newer
            )
        )
        await session.commit()

    async with httpx.AsyncClient(transport=transport(battlenet)) as http:
        game_data = AsyncClient("bnet-id", "bnet-secret", http_client=http)
        async with db_sessionmaker() as session:
            await CharactersService(session).sync_roster(game_data)

    async with db_sessionmaker() as session:
        row = (await session.execute(_character_profession_statement(TERRORSKULL, "Leatherworking"))).scalar_one()
        assert (row.skill, row.max_skill, row.scanned_at) == (999, 999, newer)
        found_from_battlenet = await GuildHubService(session).get_crafters(
            q="Handstitched Leather Boots", profession=None, game_data=None
        )
    assert found_from_battlenet.results == []


async def test_an_older_addon_scan_is_overwritten_by_battlenet(
    db_sessionmaker: async_sessionmaker[AsyncSession], battlenet: dict
) -> None:
    """An addon scan older than Battle.net's last-logout data for the same character/profession is replaced."""
    battlenet["roster"].append(roster_member("Terrorskull", "Gloomstep", rank=2, level=12))
    older = TERRORSKULL_LAST_LOGIN_AT.replace(year=TERRORSKULL_LAST_LOGIN_AT.year - 1)
    async with db_sessionmaker() as session:
        character = WowCharacter(name="Terrorskull", realm="", key=TERRORSKULL, source="import")
        session.add(character)
        await session.flush()
        session.add(
            CharacterProfession(
                character_id=character.id, profession="Leatherworking", skill=1, max_skill=1, scanned_at=older
            )
        )
        await session.commit()

    async with httpx.AsyncClient(transport=transport(battlenet)) as http:
        game_data = AsyncClient("bnet-id", "bnet-secret", http_client=http)
        async with db_sessionmaker() as session:
            await CharactersService(session).sync_roster(game_data)

    async with db_sessionmaker() as session:
        row = (await session.execute(_character_profession_statement(TERRORSKULL, "Leatherworking"))).scalar_one()
        assert (row.skill, row.max_skill, row.scanned_at) == (55, 75, TERRORSKULL_LAST_LOGIN_AT)
        found_from_battlenet = await GuildHubService(session).get_crafters(
            q="Handstitched Leather Boots", profession=None, game_data=None
        )
    assert len(found_from_battlenet.results) == 1
    assert found_from_battlenet.results[0].crafters[0].character == TERRORSKULL


async def test_unmapped_battlenet_recipe_ids_are_skipped(
    db_sessionmaker: async_sessionmaker[AsyncSession], battlenet: dict
) -> None:
    """A known recipe Battle.net reports with no entry in ``battlenet_recipe_map.json`` is never invented."""
    battlenet["roster"].append(roster_member("Mapless", "Crafter", rank=6, level=12))
    battlenet["profiles"].add("mapless-crafter")
    battlenet["profile_overrides"]["mapless-crafter"] = {
        "professions": _professions_document(
            character_id=999999,
            slug="mapless-crafter",
            name="Mapless",
            surname="Crafter",
            profession_id=165,
            profession_name="Leatherworking",
            skill=10,
            max_skill=75,
            recipes=[(1353, "Handstitched Leather Boots"), (999_999_999, "Mystery Recipe")],
        )
    }

    async with httpx.AsyncClient(transport=transport(battlenet)) as http:
        game_data = AsyncClient("bnet-id", "bnet-secret", http_client=http)
        async with db_sessionmaker() as session:
            await CharactersService(session).sync_roster(game_data)

    async with db_sessionmaker() as session:
        mapped = await GuildHubService(session).get_crafters(
            q="Handstitched Leather Boots", profession=None, game_data=None
        )
        unmapped = await GuildHubService(session).get_crafters(q="Mystery Recipe", profession=None, game_data=None)
    assert len(mapped.results) == 1
    assert mapped.results[0].crafters[0].character == "mapless-crafter"
    assert unmapped.results == []


async def test_a_professions_404_leaves_the_sync_succeeding(
    db_sessionmaker: async_sessionmaker[AsyncSession], battlenet: dict
) -> None:
    """A character under level 10, or one Battle.net hasn't published a professions document for yet, 404s on
    just that document; the rest of the roster sync still succeeds and stores no crafter row for it."""
    battlenet["roster"].append(roster_member("Noprof", "Crafter", rank=6, level=12))
    battlenet["profiles"].add("noprof-crafter")
    battlenet["profile_overrides"]["noprof-crafter"] = {"professions": None}

    async with httpx.AsyncClient(transport=transport(battlenet)) as http:
        game_data = AsyncClient("bnet-id", "bnet-secret", http_client=http)
        async with db_sessionmaker() as session:
            report = await CharactersService(session).sync_roster(game_data)

    assert report.members >= 1
    async with db_sessionmaker() as session:
        character = (await session.execute(_wow_character_statement("noprof-crafter"))).scalar_one_or_none()
    assert character is None
