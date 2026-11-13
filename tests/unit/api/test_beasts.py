"""``/api/beasts``, ``/api/beasts/{id}``, ``/api/beasts/families``, against a fake Battle.net."""

from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient

import sidequest_api.domain.beasts.services as beasts_services
from sidequest_api.app import create_app
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import TEST_API_KEY
from tests.unit.api.fake_battlenet import API, battlenet, forget_battlenet_state, transport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name


@pytest.fixture(autouse=True)
def forget_beasts_cache() -> None:
    """The beast catalog and the display-image/creature caches are process-wide; tests must not see each other's."""
    beasts_services._beasts = None
    beasts_services._display_image_cache.clear()
    beasts_services._creature_cache.clear()


def _search_hit(
    creature_id: int,
    name: str,
    *,
    family_id: int | None = None,
    family: str | None = None,
    display_id: int | None = None,
) -> dict:
    """One ``GET /data/wow/search/creature`` result: every locale's name at once, as Battle.net search indexes it."""
    data: dict = {
        "id": creature_id,
        "name": {"en_US": name},
        "type": {"id": 1, "name": {"en_US": "Beast"}},
        "is_tameable": True,
    }
    if family_id is not None:
        data["family"] = {"id": family_id, "name": {"en_US": family}}
    if display_id is not None:
        data["creature_displays"] = [{"id": display_id}]
    return {"key": {"href": f"{API}/data/wow/creature/{creature_id}"}, "data": data}


def _search_page(hits: list[dict]) -> dict:
    return {"page": 1, "pageSize": len(hits), "maxPageSize": 1000, "pageCount": 1, "results": hits}


def _creature_document(
    creature_id: int,
    name: str,
    *,
    family_id: int | None = None,
    family: str | None = None,
    display_id: int | None = None,
    is_tameable: bool = True,
) -> dict:
    """One ``GET /data/wow/creature/{id}`` document: a single locale's name, as Battle.net resolves it."""
    body: dict = {
        "_links": {"self": {"href": f"{API}/data/wow/creature/{creature_id}"}},
        "id": creature_id,
        "name": name,
        "type": {"key": {"href": f"{API}/data/wow/creature-type/1"}, "id": 1, "name": "Beast"},
        "is_tameable": is_tameable,
    }
    if family_id is not None:
        body["family"] = {
            "key": {"href": f"{API}/data/wow/creature-family/{family_id}"},
            "id": family_id,
            "name": family,
        }
    if display_id is not None:
        body["creature_displays"] = [
            {"key": {"href": f"{API}/data/wow/media/creature-display/{display_id}"}, "id": display_id}
        ]
    return body


def _display_media(display_id: int) -> dict:
    url = f"https://render.worldofwarcraft.com/forever-us/npcs/zoom/creature-display-{display_id}.jpg"
    return {
        "_links": {"self": {"href": f"{API}/data/wow/media/creature-display/{display_id}"}},
        "id": display_id,
        "assets": [{"key": "zoom", "value": url, "file_data_id": display_id}],
    }


# Forest Spider (Spider, family 1), Grizzled Timbermaw Bear and Silverback Patriarch (Bear, family 4), Ashamane and
# Barkskin Lynx (Cat, family 2); Barkskin Lynx has no display render recorded, to exercise the missing-image path.
# The last two are Blizzard placeholders Battle.net still flags tameable; no list or count may include them.
BEAST_HITS = [
    _search_hit(30, "Forest Spider", family_id=1, family="Spider", display_id=382),
    _search_hit(250063, "Grizzled Timbermaw Bear", family_id=4, family="Bear", display_id=822),
    _search_hit(729, "Silverback Patriarch", family_id=4, family="Bear", display_id=823),
    _search_hit(416, "Ashamane", family_id=2, family="Cat", display_id=2001),
    _search_hit(417, "Barkskin Lynx", family_id=2, family="Cat", display_id=None),
    _search_hit(11364, "[UNUSED] Zulian Tigress", family_id=2, family="Cat", display_id=None),
    _search_hit(1979, "TEST WOLF (ALPHA FIRST)", family_id=3, family="Wolf", display_id=None),
]


def _seed_beasts(battlenet: dict) -> None:
    battlenet["documents"]["/data/wow/search/creature"] = _search_page(BEAST_HITS)
    battlenet["documents"]["/data/wow/creature/30"] = _creature_document(
        30, "Forest Spider", family_id=1, family="Spider", display_id=382
    )
    battlenet["documents"]["/data/wow/creature/1979"] = _creature_document(
        1979, "TEST WOLF (ALPHA FIRST)", family_id=3, family="Wolf"
    )
    for display_id in (382, 822, 823, 2001):
        battlenet["documents"][f"/data/wow/media/creature-display/{display_id}"] = _display_media(display_id)


@pytest.fixture
async def beasts_client(database_url: str, battlenet: dict) -> AsyncIterator[AsyncTestClient[Litestar]]:
    _seed_beasts(battlenet)
    settings = WebSettings(_env_file=None, BATTLENET_CLIENT_ID="bnet-id", BATTLENET_CLIENT_SECRET="bnet-secret")
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        settings,
        game_data_transport=transport(battlenet),
    )
    async with AsyncTestClient(app=app) as client:
        yield client


async def test_list_beasts_sorted_by_name_with_family_and_image(beasts_client: AsyncTestClient) -> None:
    response = await beasts_client.get("/api/beasts/")
    assert response.status_code == 200
    names = [beast["name"] for beast in response.json()]
    assert names == sorted(names)
    ashamane = next(beast for beast in response.json() if beast["name"] == "Ashamane")
    assert ashamane["family_id"] == 2
    assert ashamane["family"] == "Cat"
    assert ashamane["display_id"] == 2001
    assert ashamane["image_url"] == "https://render.worldofwarcraft.com/forever-us/npcs/zoom/creature-display-2001.jpg"


async def test_list_beasts_with_no_display_has_a_null_image(beasts_client: AsyncTestClient) -> None:
    response = await beasts_client.get("/api/beasts/")
    lynx = next(beast for beast in response.json() if beast["name"] == "Barkskin Lynx")
    assert lynx["display_id"] is None
    assert lynx["image_url"] is None


async def test_blizzard_placeholder_creatures_are_left_out_of_the_list_and_lookup(
    beasts_client: AsyncTestClient,
) -> None:
    names = {beast["name"] for beast in (await beasts_client.get("/api/beasts/")).json()}
    assert names == {"Forest Spider", "Grizzled Timbermaw Bear", "Silverback Patriarch", "Ashamane", "Barkskin Lynx"}
    assert (await beasts_client.get("/api/beasts/1979")).status_code == 404


async def test_list_beasts_q_filters_by_substring_and_ranks_prefix_matches_first(
    beasts_client: AsyncTestClient,
) -> None:
    response = await beasts_client.get("/api/beasts/?q=bear")
    assert response.status_code == 200
    assert [beast["name"] for beast in response.json()] == ["Grizzled Timbermaw Bear"]

    # "as" is a substring of both, but only Ashamane starts with it.
    response = await beasts_client.get("/api/beasts/?q=as")
    assert [beast["name"] for beast in response.json()] == ["Ashamane"]


async def test_list_beasts_filtered_by_family_id(beasts_client: AsyncTestClient) -> None:
    response = await beasts_client.get("/api/beasts/?family_id=4")
    assert response.status_code == 200
    names = {beast["name"] for beast in response.json()}
    assert names == {"Grizzled Timbermaw Bear", "Silverback Patriarch"}


async def test_list_beasts_limit_caps_the_result(beasts_client: AsyncTestClient) -> None:
    response = await beasts_client.get("/api/beasts/?limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_list_beast_families_counts_tameable_beasts(beasts_client: AsyncTestClient) -> None:
    response = await beasts_client.get("/api/beasts/families")
    assert response.status_code == 200
    families = {family["name"]: family["count"] for family in response.json()}
    assert families == {"Spider": 1, "Bear": 2, "Cat": 2}
    names = [family["name"] for family in response.json()]
    assert names == sorted(names)


async def test_get_beast_returns_one_tameable_beast(beasts_client: AsyncTestClient) -> None:
    response = await beasts_client.get("/api/beasts/30")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Forest Spider"
    assert body["family"] == "Spider"
    assert body["image_url"] == "https://render.worldofwarcraft.com/forever-us/npcs/zoom/creature-display-382.jpg"


async def test_get_beast_404s_for_a_creature_battlenet_has_never_heard_of(beasts_client: AsyncTestClient) -> None:
    response = await beasts_client.get("/api/beasts/999999")
    assert response.status_code == 404


async def test_get_beast_404s_for_a_creature_that_isnt_tameable(database_url: str, battlenet: dict) -> None:
    battlenet["documents"]["/data/wow/creature/11502"] = _creature_document(11502, "Ragnaros", is_tameable=False)
    settings = WebSettings(_env_file=None, BATTLENET_CLIENT_ID="bnet-id", BATTLENET_CLIENT_SECRET="bnet-secret")
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        settings,
        game_data_transport=transport(battlenet),
    )
    async with AsyncTestClient(app=app) as client:
        response = await client.get("/api/beasts/11502")
        assert response.status_code == 404


async def test_beasts_answer_503_when_battlenet_not_configured(client: AsyncTestClient) -> None:
    assert (await client.get("/api/beasts/")).status_code == 503
    assert (await client.get("/api/beasts/30")).status_code == 503
    assert (await client.get("/api/beasts/families")).status_code == 503
