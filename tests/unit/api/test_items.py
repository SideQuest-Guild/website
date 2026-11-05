"""``/api/items``: item lookup through Postgres and Battle.net, and item search, against a fake Battle.net."""

from typing import TYPE_CHECKING

import httpx
import pytest
from litestar.testing import AsyncTestClient

from sidequest_api.app import create_app
from sidequest_api.domain.items import services as items_services
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import TEST_API_KEY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

API = "https://us.api.blizzard.com"
BETA = "static-1.60.1_70399-forever-us"
PATCH = "static-1.60.2_71000-forever-us"


def _ref(kind: str, ref_id: int, name: str, version: str) -> dict:
    return {"key": {"href": f"{API}/data/wow/{kind}/{ref_id}?namespace={version}"}, "id": ref_id, "name": name}


def _item(item_id: int, name: str, version: str) -> dict:
    """An item document shaped like Battle.net's, trimmed to what one two-handed epic sword carries."""
    media = {"key": {"href": f"{API}/data/wow/media/item/{item_id}?namespace={version}"}, "id": item_id}
    weapon_class = _ref("item-class", 2, "Weapon", version)
    sword = _ref("item-class/2/item-subclass", 8, "Sword", version)
    two_hand = {"type": "TWOHWEAPON", "name": "Two-Hand"}
    epic = {"type": "EPIC", "name": "Epic"}
    white = {"r": 255, "g": 255, "b": 255, "a": 1.0}
    return {
        "_links": {"self": {"href": f"{API}/data/wow/item/{item_id}?namespace={version}"}},
        "id": item_id,
        "name": name,
        "quality": epic,
        "level": 80,
        "required_level": 60,
        "media": media,
        "item_class": weapon_class,
        "item_subclass": sword,
        "inventory_type": two_hand,
        "is_equippable": True,
        "is_stackable": False,
        "max_count": 1,
        "purchase_price": 0,
        "purchase_quantity": 1,
        "sell_price": 123456,
        "preview_item": {
            "item": {"key": {"href": f"{API}/data/wow/item/{item_id}?namespace={version}"}, "id": item_id},
            "quality": epic,
            "name": name,
            "media": media,
            "item_class": weapon_class,
            "item_subclass": sword,
            "inventory_type": two_hand,
            "binding": {"type": "ON_ACQUIRE", "name": "Binds when picked up"},
            "weapon": {
                "damage": {
                    "min_value": 100,
                    "max_value": 200,
                    "display_string": "100 - 200 Damage",
                    "damage_class": {"type": "PHYSICAL", "name": "Physical"},
                },
                "attack_speed": {"value": 3500, "display_string": "Speed 3.50"},
                "dps": {"value": 42.9, "display_string": "(42.9 damage per second)"},
            },
            "stats": [
                {
                    "type": {"type": "STRENGTH", "name": "Strength"},
                    "value": 20,
                    "display": {"display_string": "+20 Strength", "color": white},
                }
            ],
            "requirements": {"level": {"value": 60, "display_string": "Requires Level 60"}},
            "durability": {"value": 120, "display_string": "Durability 120 / 120"},
            "level": {"value": 80, "display_string": "Item Level 80"},
        },
    }


def _search_hit(item_id: int, name: str, version: str) -> dict:
    return {
        "key": {"href": f"{API}/data/wow/item/{item_id}?namespace={version}"},
        "data": {
            "id": item_id,
            "name": {"en_US": name, "de_DE": name},
            "quality": {"type": "EPIC", "name": {"en_US": "Epic"}},
            "level": 80,
            "required_level": 60,
            "media": {"id": item_id},
            "item_class": {"id": 2, "name": {"en_US": "Weapon"}},
            "item_subclass": {"id": 8, "name": {"en_US": "Sword"}},
            "inventory_type": {"type": "TWOHWEAPON", "name": {"en_US": "Two-Hand"}},
            "is_equippable": True,
            "is_stackable": False,
            "max_count": 1,
            "purchase_price": 0,
            "purchase_quantity": 1,
            "sell_price": 123456,
        },
    }


@pytest.fixture
def battlenet() -> dict:
    """What the fake Battle.net serves, and every API request it saw. Tests change it between calls."""
    return {
        "version": BETA,
        "items": {19019: "Thunderfury, Blessed Blade of the Windseeker"},
        "search": [(19019, "Thunderfury, Blessed Blade of the Windseeker")],
        "down": False,
        "requests": [],
    }


def _transport(battlenet: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth.battle.net":
            return httpx.Response(200, json={"access_token": "app-token", "token_type": "bearer", "expires_in": 86399})
        battlenet["requests"].append(request)
        if battlenet["down"]:
            return httpx.Response(503, json={"code": 503})
        path, version = request.url.path, battlenet["version"]
        if path == "/data/wow/search/item":
            hits = [_search_hit(item_id, name, version) for item_id, name in battlenet["search"]]
            body = {"page": 1, "pageSize": 50, "maxPageSize": 1000, "pageCount": 1, "results": hits}
            return httpx.Response(200, json=body)
        kind, _, raw_id = path.removeprefix("/data/wow/").rpartition("/")
        item_id = int(raw_id) if raw_id.isdigit() else 0
        if item_id not in battlenet["items"]:
            return httpx.Response(404, json={"code": 404})
        if kind == "media/item":
            icon = {"key": "icon", "value": f"https://render.worldofwarcraft.com/forever-us/icons/56/{item_id}.jpg"}
            body = {
                "_links": {"self": {"href": f"{API}{path}"}},
                "id": item_id,
                "assets": [{**icon, "file_data_id": 1}],
            }
            return httpx.Response(200, json=body)
        return httpx.Response(200, json=_item(item_id, battlenet["items"][item_id], version))

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _forget_battlenet_state() -> None:
    """The data version and the search cache are process-wide; tests must not see each other's."""
    items_services._data_version = None
    items_services._search_cache.clear()


@pytest.fixture
async def items_client(database_url: str, battlenet: dict) -> AsyncIterator[AsyncTestClient[Litestar]]:
    settings = WebSettings(_env_file=None, BATTLENET_CLIENT_ID="bnet-id", BATTLENET_CLIENT_SECRET="bnet-secret")
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        settings,
        game_data_transport=_transport(battlenet),
    )
    async with AsyncTestClient(app=app) as client:
        yield client


def _item_requests(battlenet: dict) -> list[str]:
    return [request.url.path for request in battlenet["requests"] if request.url.path.startswith("/data/wow/item/")]


async def test_an_item_is_fetched_once_then_served_from_the_database(
    items_client: AsyncTestClient, battlenet: dict
) -> None:
    first = await items_client.get("/api/items/19019")
    second = await items_client.get("/api/items/19019")

    assert first.status_code == 200
    assert first.json() == second.json()
    body = first.json()
    assert body["name"] == "Thunderfury, Blessed Blade of the Windseeker"
    assert (body["quality"], body["quality_name"]) == ("EPIC", "Epic")
    assert (body["inventory_type"], body["item_subclass"], body["item_level"]) == ("TWOHWEAPON", "Sword", 80)
    assert body["icon_url"] == "https://render.worldofwarcraft.com/forever-us/icons/56/19019.jpg"
    assert body["tooltip"] == [
        "Item Level 80",
        "Binds when picked up",
        "Two-Hand · Sword",
        "100 - 200 Damage",
        "Speed 3.50",
        "(42.9 damage per second)",
        "+20 Strength",
        "Durability 120 / 120",
        "Requires Level 60",
    ]
    assert _item_requests(battlenet) == ["/data/wow/item/19019"]
    assert first.headers["Cloudflare-CDN-Cache-Control"].startswith("max-age=3600")
    assert "set-cookie" not in first.headers


async def test_an_unknown_item_is_not_found(items_client: AsyncTestClient) -> None:
    response = await items_client.get("/api/items/424242")

    assert response.status_code == 404


async def test_a_new_data_version_fetches_stored_items_again(items_client: AsyncTestClient, battlenet: dict) -> None:
    await items_client.get("/api/items/19019")
    battlenet["version"] = PATCH
    battlenet["items"][19019] = "Thunderfury, Blessed Blade of the Windseeker (patched)"
    await items_client.get("/api/items", params={"q": "Thunderfury"})  # first sight of the new data version

    response = await items_client.get("/api/items/19019")

    assert response.json()["name"] == "Thunderfury, Blessed Blade of the Windseeker (patched)"
    assert _item_requests(battlenet) == ["/data/wow/item/19019", "/data/wow/item/19019"]


async def test_a_stored_item_is_served_while_battlenet_is_down(items_client: AsyncTestClient, battlenet: dict) -> None:
    await items_client.get("/api/items/19019")
    battlenet["version"] = PATCH
    await items_client.get("/api/items", params={"q": "Thunderfury"})
    battlenet["down"] = True

    stored = await items_client.get("/api/items/19019")
    never_stored = await items_client.get("/api/items/20000")

    assert stored.status_code == 200
    assert stored.json()["name"] == "Thunderfury, Blessed Blade of the Windseeker"
    assert never_stored.status_code == 503


async def test_items_answer_503_when_battlenet_is_not_configured(client: AsyncTestClient) -> None:
    assert (await client.get("/api/items/19019")).status_code == 503
    assert (await client.get("/api/items", params={"q": "Thunderfury"})).status_code == 503


async def test_search_returns_matches_and_sends_the_filters(items_client: AsyncTestClient, battlenet: dict) -> None:
    battlenet["search"] = [(19019, "Thunderfury, Blessed Blade of the Windseeker"), (289294, "Thunderfury Copy")]

    response = await items_client.get(
        "/api/items", params={"q": "thunder", "quality": ["LEGENDARY", "EPIC"], "slot": "TWOHWEAPON"}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["page"], body["page_count"]) == (1, 1)
    assert [result["item_id"] for result in body["results"]] == [19019, 289294]
    assert body["results"][0] == {
        "item_id": 19019,
        "name": "Thunderfury, Blessed Blade of the Windseeker",
        "quality": "EPIC",
        "quality_name": "Epic",
        "inventory_type": "TWOHWEAPON",
        "inventory_type_name": "Two-Hand",
        "item_level": 80,
        "required_level": 60,
    }
    sent = battlenet["requests"][-1].url.params
    assert sent["name.en_US"] == "thunder"
    assert sent["quality.type"] == "EPIC||LEGENDARY"
    assert sent["inventory_type.type"] == "TWOHWEAPON"


async def test_the_same_search_is_answered_from_cache(items_client: AsyncTestClient, battlenet: dict) -> None:
    await items_client.get("/api/items", params={"q": "Thunder"})
    await items_client.get("/api/items", params={"q": "thunder"})

    assert len([r for r in battlenet["requests"] if r.url.path == "/data/wow/search/item"]) == 1


@pytest.mark.parametrize(
    "params", [{"q": "th"}, {"q": "thunder", "quality": "SHINY"}, {"q": "thunder", "slot": "two-hand"}]
)
async def test_search_rejects_bad_parameters(items_client: AsyncTestClient, params: dict) -> None:
    assert (await items_client.get("/api/items", params=params)).status_code == 400
