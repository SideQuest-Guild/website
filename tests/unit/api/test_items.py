"""``/api/items``: item lookup through Postgres and Battle.net, and item search, against a fake Battle.net."""

from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient

from sidequest_api.app import create_app
from sidequest_common.schemas import ItemLootPrice, sql_price
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import TEST_API_KEY
from tests.unit.api.fake_battlenet import PATCH, THUNDERFURY, battlenet, forget_battlenet_state, transport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name


@pytest.fixture
async def items_client(database_url: str, battlenet: dict) -> AsyncIterator[AsyncTestClient[Litestar]]:
    settings = WebSettings(_env_file=None, BATTLENET_CLIENT_ID="bnet-id", BATTLENET_CLIENT_SECRET="bnet-secret")
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        settings,
        game_data_transport=transport(battlenet),
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
    assert body["name"] == THUNDERFURY
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
    battlenet["items"][19019] = f"{THUNDERFURY} (patched)"
    await items_client.get("/api/items", params={"q": "Thunderfury"})  # first sight of the new data version

    response = await items_client.get("/api/items/19019")

    assert response.json()["name"] == f"{THUNDERFURY} (patched)"
    assert _item_requests(battlenet) == ["/data/wow/item/19019", "/data/wow/item/19019"]


async def test_a_stored_item_is_served_while_battlenet_is_down(items_client: AsyncTestClient, battlenet: dict) -> None:
    await items_client.get("/api/items/19019")
    battlenet["version"] = PATCH
    await items_client.get("/api/items", params={"q": "Thunderfury"})
    battlenet["down"] = True

    stored = await items_client.get("/api/items/19019")
    never_stored = await items_client.get("/api/items/20000")

    assert stored.status_code == 200
    assert stored.json()["name"] == THUNDERFURY
    assert never_stored.status_code == 503


async def test_items_answer_503_when_battlenet_is_not_configured(client: AsyncTestClient) -> None:
    assert (await client.get("/api/items/19019")).status_code == 503
    assert (await client.get("/api/items", params={"q": "Thunderfury"})).status_code == 503


async def test_search_returns_matches_and_sends_the_filters(items_client: AsyncTestClient, battlenet: dict) -> None:
    battlenet["search"] = [(19019, THUNDERFURY), (289294, "Thunderfury Copy")]

    response = await items_client.get(
        "/api/items", params={"q": "thunder", "quality": ["LEGENDARY", "EPIC"], "slot": "TWOHWEAPON"}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["page"], body["page_count"]) == (1, 1)
    assert [result["item_id"] for result in body["results"]] == [19019, 289294]
    assert body["results"][0] == {
        "item_id": 19019,
        "name": THUNDERFURY,
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


async def test_an_item_carries_its_sql_price(items_client: AsyncTestClient) -> None:
    body = (await items_client.get("/api/items/19019")).json()

    assert body["loot_price"] == {"main_spec": 200, "off_spec": 20, "chase": 300}


@pytest.mark.parametrize(
    ("inventory_type", "quality", "price"),
    [
        ("TWOHWEAPON", "EPIC", ItemLootPrice(main_spec=200, off_spec=20, chase=300)),
        ("HAND", "EPIC", ItemLootPrice(main_spec=75, off_spec=8, chase=113)),
        ("CLOAK", "RARE", ItemLootPrice(main_spec=55, off_spec=6, chase=83)),
        ("NON_EQUIP", "LEGENDARY", ItemLootPrice(main_spec=300, off_spec=30, chase=300)),
        ("WEAPON", "LEGENDARY", ItemLootPrice(main_spec=300, off_spec=30, chase=300)),
        ("BODY", "EPIC", None),
        ("NON_EQUIP", "EPIC", None),
    ],
)
def test_sql_price_follows_the_loot_rules(inventory_type: str, quality: str, price: ItemLootPrice | None) -> None:
    assert sql_price(inventory_type, quality) == price
