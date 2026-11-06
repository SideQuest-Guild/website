"""``/api/professions``, ``/api/recipes``, ``/api/game/classes``, and the crafters profession+name matching, against
a fake Battle.net."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest
from litestar.testing import AsyncTestClient
from wow import AsyncClient

import sidequest_api.domain.game_reference.services as game_reference_services
from sidequest_api.app import create_app
from sidequest_api.domain.guild_hub.services import GuildHubService
from sidequest_common.models import CharacterProfession, CharacterRecipeLink, Member, ProfessionRecipe, WowCharacter
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import TEST_API_KEY
from tests.unit.api.fake_battlenet import API, BETA, battlenet, forget_battlenet_state, transport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name


@pytest.fixture(autouse=True)
def forget_game_reference_cache() -> None:
    """The profession/recipe and class catalogs are process-wide; tests must not see each other's."""
    game_reference_services._catalog = None
    game_reference_services._classes = None
    game_reference_services._recipe_cache.clear()


def _ref(kind: str, ref_id: int, name: str) -> dict:
    return {"key": {"href": f"{API}/data/wow/{kind}/{ref_id}?namespace={BETA}"}, "id": ref_id, "name": name}


def _media(mid: int, icon_url: str) -> dict:
    return {
        "_links": {"self": {"href": f"{API}/data/wow/media/x/{mid}?namespace={BETA}"}},
        "id": mid,
        "assets": [{"key": "icon", "value": icon_url, "file_data_id": mid}],
    }


def _profession_index(professions: list[tuple[int, str]]) -> dict:
    return {
        "_links": {"self": {"href": f"{API}/data/wow/profession/?namespace={BETA}"}},
        "professions": [_ref("profession", pid, name) for pid, name in professions],
    }


def _profession(pid: int, name: str, kind: str, tier_id: int) -> dict:
    return {
        "_links": {"self": {"href": f"{API}/data/wow/profession/{pid}?namespace={BETA}"}},
        "id": pid,
        "name": name,
        "description": f"{name} description",
        "type": {"type": kind, "name": kind.title()},
        "media": {"id": pid, "key": {"href": f"{API}/data/wow/media/profession/{pid}?namespace={BETA}"}},
        "skill_tiers": [_ref(f"profession/{pid}/skill-tier", tier_id, f"{name} Skill")],
    }


def _skill_tier(tier_id: int, categories: list[tuple[str, list[tuple[int, str]]]]) -> dict:
    return {
        "_links": {"self": {"href": f"{API}/data/wow/profession/x/skill-tier/{tier_id}?namespace={BETA}"}},
        "id": tier_id,
        "name": "Skill tier",
        "minimum_skill_level": 1,
        "maximum_skill_level": 300,
        "categories": [
            {"name": cat_name, "recipes": [_ref("recipe", rid, rname) for rid, rname in recipes]}
            for cat_name, recipes in categories
        ],
    }


def _recipe(
    rid: int,
    name: str,
    *,
    crafted_item: tuple[int, str] | None = None,
    reagents: list[tuple[int, str, int]] | None = None,
    crafted_quantity: dict | None = None,
    rank: int | None = None,
    description: str | None = None,
) -> dict:
    body: dict = {
        "_links": {"self": {"href": f"{API}/data/wow/recipe/{rid}?namespace={BETA}"}},
        "id": rid,
        "name": name,
        "media": {"id": rid, "key": {"href": f"{API}/data/wow/media/recipe/{rid}?namespace={BETA}"}},
        "reagents": [{"quantity": qty, "reagent": _ref("item", iid, iname)} for iid, iname, qty in (reagents or [])],
    }
    if crafted_item is not None:
        body["crafted_item"] = _ref("item", crafted_item[0], crafted_item[1])
    if crafted_quantity is not None:
        body["crafted_quantity"] = crafted_quantity
    if rank is not None:
        body["rank"] = rank
    if description is not None:
        body["description"] = description
    return body


def _class_index(classes: list[tuple[int, str]]) -> dict:
    return {
        "_links": {"self": {"href": f"{API}/data/wow/playable-class/?namespace={BETA}"}},
        "classes": [_ref("playable-class", cid, name) for cid, name in classes],
    }


def _playable_class(cid: int, name: str, specs: list[tuple[int, str]]) -> dict:
    return {
        "_links": {"self": {"href": f"{API}/data/wow/playable-class/{cid}?namespace={BETA}"}},
        "id": cid,
        "name": name,
        "gender_name": {"male": name, "female": name},
        "power_type": _ref("power-type", 0, "Mana"),
        "specializations": [_ref("playable-specialization", sid, sname) for sid, sname in specs],
        "media": {"id": cid, "key": {"href": f"{API}/data/wow/media/playable-class/{cid}?namespace={BETA}"}},
        "playable_races": [],
    }


def _spec(sid: int, name: str, class_ref: tuple[int, str]) -> dict:
    return {
        "_links": {"self": {"href": f"{API}/data/wow/playable-specialization/{sid}?namespace={BETA}"}},
        "id": sid,
        "name": name,
        "playable_class": _ref("playable-class", *class_ref),
        "power_type": _ref("power-type", 0, "Mana"),
        "media": {"id": sid, "key": {"href": f"{API}/data/wow/media/playable-specialization/{sid}?namespace={BETA}"}},
        "spec_talent_tree": {
            "key": {"href": f"{API}/data/wow/talent-tree/1/playable-specialization/{sid}"},
            "name": name,
        },
    }


def _seed_two_professions(battlenet: dict) -> None:
    """Alchemy (171) and Tailoring (197), each with one recipe literally named "Widget", plus Alchemy's "Flask of
    the Titans" (3372) and Blacksmithing's "Copper Chain Pants" matching the guild crafters fixture."""
    battlenet["documents"].update(
        {
            "/data/wow/profession/index": _profession_index(
                [(171, "Alchemy"), (197, "Tailoring"), (164, "Blacksmithing")]
            ),
            "/data/wow/profession/171": _profession(171, "Alchemy", "PRIMARY", 2101),
            "/data/wow/profession/197": _profession(197, "Tailoring", "PRIMARY", 2102),
            "/data/wow/profession/164": _profession(164, "Blacksmithing", "PRIMARY", 2103),
            "/data/wow/media/profession/171": _media(171, "https://render/alchemy.jpg"),
            "/data/wow/media/profession/197": _media(197, "https://render/tailoring.jpg"),
            "/data/wow/media/profession/164": _media(164, "https://render/blacksmithing.jpg"),
            "/data/wow/profession/171/skill-tier/2101": _skill_tier(
                2101, [("Flasks", [(3372, "Flask of the Titans"), (5001, "Widget")])]
            ),
            "/data/wow/profession/197/skill-tier/2102": _skill_tier(2102, [("Cloth", [(5002, "Widget")])]),
            "/data/wow/profession/164/skill-tier/2103": _skill_tier(2103, [("Armor", [(2662, "Copper Chain Pants")])]),
            "/data/wow/recipe/3372": _recipe(
                3372,
                "Flask of the Titans",
                crafted_item=(13510, "Flask of the Titans"),
                reagents=[(3372001, "Elixir of Giants", 2)],
                crafted_quantity={"value": 1.0},
                rank=1,
                description="A powerful flask.",
            ),
            "/data/wow/media/recipe/3372": _media(3372, "https://render/flask.jpg"),
            "/data/wow/recipe/5001": _recipe(5001, "Widget"),
            "/data/wow/media/recipe/5001": _media(5001, "https://render/widget1.jpg"),
            "/data/wow/recipe/5002": _recipe(5002, "Widget"),
            "/data/wow/media/recipe/5002": _media(5002, "https://render/widget2.jpg"),
            "/data/wow/recipe/2662": _recipe(
                2662, "Copper Chain Pants", crafted_item=(2852, "Copper Chain Pants"), reagents=[]
            ),
            "/data/wow/media/recipe/2662": _media(2662, "https://render/pants.jpg"),
        }
    )
    battlenet["items"].update({13510: "Flask of the Titans", 3372001: "Elixir of Giants"})


def _seed_classes(battlenet: dict) -> None:
    battlenet["documents"].update(
        {
            "/data/wow/playable-class/index": _class_index([(1, "Warrior"), (8, "Mage")]),
            "/data/wow/playable-class/1": _playable_class(1, "Warrior", [(71, "Arms")]),
            "/data/wow/playable-class/8": _playable_class(8, "Mage", [(62, "Arcane")]),
            "/data/wow/media/playable-class/1": _media(1, "https://render/warrior.jpg"),
            "/data/wow/media/playable-class/8": _media(8, "https://render/mage.jpg"),
            "/data/wow/playable-specialization/71": _spec(71, "Arms", (1, "Warrior")),
            "/data/wow/playable-specialization/62": _spec(62, "Arcane", (8, "Mage")),
            "/data/wow/media/playable-specialization/71": _media(71, "https://render/arms.jpg"),
            "/data/wow/media/playable-specialization/62": _media(62, "https://render/arcane.jpg"),
        }
    )


@pytest.fixture
async def recipes_client(database_url: str, battlenet: dict) -> AsyncIterator[AsyncTestClient[Litestar]]:
    _seed_two_professions(battlenet)
    _seed_classes(battlenet)
    settings = WebSettings(_env_file=None, BATTLENET_CLIENT_ID="bnet-id", BATTLENET_CLIENT_SECRET="bnet-secret")
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        settings,
        game_data_transport=transport(battlenet),
    )
    async with AsyncTestClient(app=app) as client:
        yield client


async def _seed_crafter(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    character_key: str,
    profession: str,
    recipe_game_id: int,
    recipe_name: str,
    member_id: int | None = None,
    item_id: int | None = None,
    skill: int = 150,
) -> None:
    async with db_sessionmaker() as session:
        character = WowCharacter(
            name=character_key.split("-")[0], realm="Whitemane", key=character_key, member_id=member_id, source="claim"
        )
        session.add(character)
        await session.flush()
        cp = CharacterProfession(
            character_id=character.id, profession=profession, skill=skill, max_skill=300, scanned_at=datetime.now(UTC)
        )
        session.add(cp)
        await session.flush()
        recipe = ProfessionRecipe(recipe_id=recipe_game_id, name=recipe_name, item_id=item_id)
        session.add(recipe)
        await session.flush()
        session.add(CharacterRecipeLink(profession_id=cp.id, recipe_id=recipe.id))
        await session.commit()


# --- /api/professions and /api/professions/{id} ---------------------------------------------------------------


async def test_list_professions_returns_type_icon_and_skill_tier(recipes_client: AsyncTestClient) -> None:
    response = await recipes_client.get("/api/professions/")
    assert response.status_code == 200, response.text
    body = response.json()
    alchemy = next(p for p in body if p["name"] == "Alchemy")
    assert alchemy == {
        "id": 171,
        "name": "Alchemy",
        "type": "PRIMARY",
        "icon_url": "https://render/alchemy.jpg",
        "skill_tier_id": 2101,
    }


async def test_get_profession_returns_categories_with_recipes(recipes_client: AsyncTestClient) -> None:
    response = await recipes_client.get("/api/professions/171")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profession_name"] == "Alchemy"
    assert body["categories"][0]["name"] == "Flasks"
    assert {"id": 3372, "name": "Flask of the Titans"} in body["categories"][0]["recipes"]


async def test_get_unknown_profession_is_404(recipes_client: AsyncTestClient) -> None:
    response = await recipes_client.get("/api/professions/999999")
    assert response.status_code == 404


# --- /api/recipes/{id} ------------------------------------------------------------------------------------------


async def test_recipe_with_a_crafted_item_shows_item_reagents_and_quantity(recipes_client: AsyncTestClient) -> None:
    response = await recipes_client.get("/api/recipes/3372")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Flask of the Titans"
    assert body["profession"] == "Alchemy"
    assert body["crafted_item"] == {"item_id": 13510, "name": "Flask of the Titans", "quality": "EPIC"}
    assert body["crafted_quantity"] == "Makes 1"
    assert body["rank"] == 1
    assert body["reagents"] == [{"item_id": 3372001, "name": "Elixir of Giants", "quantity": 2, "quality": "EPIC"}]


async def test_recipe_with_no_crafted_item_has_a_null_crafted_item(recipes_client: AsyncTestClient) -> None:
    response = await recipes_client.get("/api/recipes/5001")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["crafted_item"] is None
    assert body["crafted_quantity"] is None


async def test_unknown_recipe_is_404(recipes_client: AsyncTestClient) -> None:
    response = await recipes_client.get("/api/recipes/999999")
    assert response.status_code == 404


async def test_recipes_answer_503_when_battlenet_not_configured(client: AsyncTestClient) -> None:
    assert (await client.get("/api/recipes/3372")).status_code == 503
    assert (await client.get("/api/professions/171")).status_code == 503
    assert (await client.get("/api/game/classes")).status_code == 503


async def test_recipe_crafters_matched_by_profession_and_casefolded_name(
    recipes_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_crafter(
        db_sessionmaker,
        character_key="wanderalt-whitemane",
        profession="Alchemy",
        recipe_game_id=9001,
        recipe_name="flask of the titans",
        member_id=None,
        skill=275,
    )
    response = await recipes_client.get("/api/recipes/3372")
    assert response.status_code == 200, response.text
    crafters = response.json()["crafters"]
    assert len(crafters) == 1
    assert crafters[0]["character"] == "wanderalt-whitemane"
    assert crafters[0]["skill"] == 275


async def test_same_recipe_name_in_two_professions_does_not_cross_match(
    recipes_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_crafter(
        db_sessionmaker,
        character_key="tailor-whitemane",
        profession="Tailoring",
        recipe_game_id=9100,
        recipe_name="Widget",
    )
    # Alchemy's "Widget" (5001) must not see Tailoring's crafter.
    response = await recipes_client.get("/api/recipes/5001")
    assert response.status_code == 200, response.text
    assert response.json()["crafters"] == []
    # Tailoring's "Widget" (5002) does.
    response = await recipes_client.get("/api/recipes/5002")
    assert response.status_code == 200, response.text
    assert response.json()["crafters"][0]["character"] == "tailor-whitemane"


# --- /api/game/classes -------------------------------------------------------------------------------------------


async def test_list_game_classes_returns_specs_and_icons(recipes_client: AsyncTestClient) -> None:
    response = await recipes_client.get("/api/game/classes")
    assert response.status_code == 200, response.text
    body = response.json()
    warrior = next(c for c in body if c["class"] == "warrior")
    assert warrior["name"] == "Warrior"
    assert warrior["icon_url"] == "https://render/warrior.jpg"
    assert warrior["specs"] == [{"id": 71, "name": "Arms", "icon_url": "https://render/arms.jpg"}]


# --- GET /api/guild/crafters' battlenet_recipe_id enrichment -----------------------------------------------------


async def test_guild_crafters_battlenet_recipe_id_resolves_and_tolerates_down(
    db_sessionmaker: async_sessionmaker[AsyncSession], battlenet: dict
) -> None:
    _seed_two_professions(battlenet)
    async with db_sessionmaker() as session:
        member = Member(discord_id=9001, username="wanderer", global_name="Wanderer", is_guild_member=True)
        session.add(member)
        await session.flush()
        character = WowCharacter(
            name="Wanderalt", realm="Whitemane", key="wanderalt-whitemane", member_id=member.id, source="claim"
        )
        session.add(character)
        await session.flush()
        cp = CharacterProfession(
            character_id=character.id, profession="Alchemy", skill=275, max_skill=300, scanned_at=datetime.now(UTC)
        )
        session.add(cp)
        await session.flush()
        recipe = ProfessionRecipe(recipe_id=9001, name="Flask of the Titans", item_id=13510)
        session.add(recipe)
        await session.flush()
        session.add(CharacterRecipeLink(profession_id=cp.id, recipe_id=recipe.id))
        await session.commit()

    async with httpx.AsyncClient(transport=transport(battlenet)) as http:
        game_data = AsyncClient("bnet-id", "bnet-secret", http_client=http)
        async with db_sessionmaker() as session:
            result = await GuildHubService(session).get_crafters(q="Flask", profession=None, game_data=game_data)
        assert result.results[0].battlenet_recipe_id == 3372

    battlenet["down"] = True
    game_reference_services._catalog = None
    async with httpx.AsyncClient(transport=transport(battlenet)) as http:
        game_data = AsyncClient("bnet-id", "bnet-secret", http_client=http)
        async with db_sessionmaker() as session:
            result = await GuildHubService(session).get_crafters(q="Flask", profession=None, game_data=game_data)
        assert result.results[0].battlenet_recipe_id is None


async def test_guild_crafters_battlenet_recipe_id_is_null_without_game_data(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_crafter(
        db_sessionmaker,
        character_key="solo-whitemane",
        profession="Blacksmithing",
        recipe_game_id=2662,
        recipe_name="Copper Chain Pants",
    )
    async with db_sessionmaker() as session:
        result = await GuildHubService(session).get_crafters(q="Copper", profession=None, game_data=None)
    assert result.results[0].battlenet_recipe_id is None
