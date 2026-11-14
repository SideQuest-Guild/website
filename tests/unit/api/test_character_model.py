"""``/api/characters/{slug}/model`` and ``/api/modelviewer/{path}``, against fake Battle.net and Wowhead.

The appearance is Terrorskull Gloomstep's real Battle.net recording: an Undead male rogue with a dagger in each hand
and a bow in the ranged slot. Wowhead's item looks below are the real ones for his items.
"""

import copy
from typing import TYPE_CHECKING

import httpx
import pytest
from litestar.testing import AsyncTestClient

from sidequest_api.app import create_app
from sidequest_api.lib import wowhead
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import TEST_API_KEY
from tests.unit.api.fake_battlenet import TERRORSKULL, battlenet, forget_battlenet_state, recorded_document, transport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name

# item id -> (display id, inventory type), as Wowhead's item XML gives them.
ITEM_LOOKS = {
    273645: (737427, 1),  # head
    5964: (9544, 3),  # shoulders
    2105: (10005, 4),  # shirt
    7374: (8071, 5),  # chest
    6468: (9748, 6),  # waist
    9624: (5469, 7),  # legs
    7751: (9169, 8),  # feet
    15351: (27699, 9),  # wrists
    4107: (4438, 10),  # hands
    279179: (741400, 16),  # cloak
    8006: (20326, 13),  # one-hand dagger, main hand
    9453: (20595, 13),  # one-hand dagger, off hand
    17686: (675201, 15),  # bow
    2129: (18662, 14),  # a shield
}
NECK, RING, TRINKET = 273088, 17694, 3456


@pytest.fixture(autouse=True)
def forget_item_looks() -> None:
    """Wowhead item looks are cached process-wide; tests must not see each other's."""
    wowhead._item_looks.clear()


@pytest.fixture
def wowhead_state() -> dict:
    """What the fake Wowhead serves: item looks, viewer files by path, and whether it's failing; plus every request."""
    return {"looks": dict(ITEM_LOOKS), "files": {}, "status": None, "requests": []}


def _wowhead_transport(state: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        if state["status"] is not None:
            return httpx.Response(state["status"])
        if request.url.host == "www.wowhead.com":
            item_id = int(request.url.path.removeprefix("/forever/item=").removesuffix("&xml"))
            if item_id not in state["looks"]:
                return httpx.Response(200, text="<wowhead><error>Item not found!</error></wowhead>")
            display_id, inventory_type = state["looks"][item_id]
            xml = (
                f'<wowhead><item id="{item_id}"><icon displayId="{display_id}">inv_x</icon>'
                f'<inventorySlot id="{inventory_type}">Slot</inventorySlot></item></wowhead>'
            )
            return httpx.Response(200, text=xml)
        path = request.url.path.removeprefix("/modelviewer/classicplus/")
        if path not in state["files"]:
            return httpx.Response(404, text="Not Found")
        body, content_type = state["files"][path]
        headers = {"content-type": content_type, "etag": '"v1"'}
        return httpx.Response(200, stream=httpx.ByteStream(body), headers=headers)

    return httpx.MockTransport(handler)


@pytest.fixture
async def model_client(
    database_url: str, battlenet: dict, wowhead_state: dict
) -> AsyncIterator[AsyncTestClient[Litestar]]:
    settings = WebSettings(_env_file=None, BATTLENET_CLIENT_ID="bnet-id", BATTLENET_CLIENT_SECRET="bnet-secret")
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        settings,
        game_data_transport=transport(battlenet),
        wowhead_transport=_wowhead_transport(wowhead_state),
    )
    async with AsyncTestClient(app=app) as client:
        yield client


def _appearance(**changes: object) -> dict:
    """Terrorskull's recorded appearance, with top-level fields replaced."""
    body = copy.deepcopy(recorded_document(f"wow/character/{TERRORSKULL}/appearance"))
    body.update(changes)
    return body


def _items_requested(wowhead_state: dict) -> set[int]:
    return {
        int(request.url.path.removeprefix("/forever/item=").removesuffix("&xml"))
        for request in wowhead_state["requests"]
        if request.url.host == "www.wowhead.com"
    }


async def test_model_draws_body_barber_choices_and_worn_items(
    model_client: AsyncTestClient, wowhead_state: dict
) -> None:
    response = await model_client.get(f"/api/characters/{TERRORSKULL}/model")
    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == 9  # Undead (5) male
    assert {"option_id": 60, "choice_id": 944} in body["customizations"]  # Hair Style: Spiked
    assert len(body["customizations"]) == 9
    slots = {item["slot"]: item["display_id"] for item in body["items"]}
    # Each dagger goes in the viewer's own hand slot, not its one-hand inventory type (13), and the bow stays
    # sheathed out of sight while the hands are full.
    assert slots == {
        1: 737427,
        3: 9544,
        4: 10005,
        5: 8071,
        6: 9748,
        7: 5469,
        8: 9169,
        9: 27699,
        10: 4438,
        16: 741400,
        21: 20326,
        22: 20595,
    }
    # Necks, rings and trinkets never show on a body, so Wowhead is never asked about them.
    assert _items_requested(wowhead_state).isdisjoint({NECK, RING, TRINKET})


async def test_shield_keeps_its_slot_and_ranged_shows_when_hands_are_empty(
    model_client: AsyncTestClient, battlenet: dict
) -> None:
    recorded = _appearance()["items"]
    with_shield = [
        {**item, "id": 2129} if item["slot"]["type"] == "OFF_HAND" else item
        for item in recorded
        if item["slot"]["type"] != "MAIN_HAND"
    ]
    battlenet["profile_overrides"][TERRORSKULL] = {"appearance": _appearance(items=with_shield)}
    slots = {item["slot"] for item in (await model_client.get(f"/api/characters/{TERRORSKULL}/model")).json()["items"]}
    assert 14 in slots
    assert 22 not in slots
    assert 15 not in slots  # a shield is still a hand holding something

    bare_hands = [item for item in recorded if item["slot"]["type"] not in {"MAIN_HAND", "OFF_HAND"}]
    battlenet["profile_overrides"][TERRORSKULL] = {"appearance": _appearance(items=bare_hands)}
    slots = {item["slot"] for item in (await model_client.get(f"/api/characters/{TERRORSKULL}/model")).json()["items"]}
    assert 15 in slots


async def test_female_body_and_items_wowhead_cannot_draw(
    model_client: AsyncTestClient, battlenet: dict, wowhead_state: dict
) -> None:
    del wowhead_state["looks"][273645]  # the helm: Wowhead has no such item
    battlenet["profile_overrides"][TERRORSKULL] = {
        "appearance": _appearance(gender={"type": "FEMALE", "name": "Female"})
    }
    body = (await model_client.get(f"/api/characters/{TERRORSKULL}/model")).json()
    assert body["model_id"] == 10
    assert 1 not in {item["slot"] for item in body["items"]}
    assert 5 in {item["slot"] for item in body["items"]}


async def test_a_failed_wowhead_lookup_is_asked_again_next_time(
    model_client: AsyncTestClient, wowhead_state: dict
) -> None:
    wowhead_state["status"] = 503
    body = (await model_client.get(f"/api/characters/{TERRORSKULL}/model")).json()
    assert body["items"] == []
    wowhead_state["status"] = None
    body = (await model_client.get(f"/api/characters/{TERRORSKULL}/model")).json()
    assert len(body["items"]) == 12


async def test_model_404s_without_a_character_or_for_a_race_the_viewer_lacks(
    model_client: AsyncTestClient, battlenet: dict
) -> None:
    assert (await model_client.get("/api/characters/nobody-nowhere/model")).status_code == 404
    race = {"key": {"href": "https://example.invalid"}, "id": 52, "name": "Dracthyr"}
    battlenet["profile_overrides"][TERRORSKULL] = {"appearance": _appearance(playable_race=race)}
    assert (await model_client.get(f"/api/characters/{TERRORSKULL}/model")).status_code == 404


async def test_model_503s_when_battlenet_is_down(model_client: AsyncTestClient, battlenet: dict) -> None:
    battlenet["down"] = True
    assert (await model_client.get(f"/api/characters/{TERRORSKULL}/model")).status_code == 503


async def test_viewer_file_is_relayed_with_long_cache_headers(
    model_client: AsyncTestClient, wowhead_state: dict
) -> None:
    wowhead_state["files"]["meta/armor/5/8071.json"] = (b'{"Item": null}', "application/json")
    response = await model_client.get("/api/modelviewer/meta/armor/5/8071.json")
    assert response.status_code == 200
    assert response.content == b'{"Item": null}'
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "public, max-age=604800"
    assert response.headers["etag"] == '"v1"'
    assert "set-cookie" not in response.headers


async def test_viewer_file_missing_at_wowhead_404s_and_wowhead_failing_502s(
    model_client: AsyncTestClient, wowhead_state: dict
) -> None:
    assert (await model_client.get("/api/modelviewer/m2/1.m2")).status_code == 404
    wowhead_state["status"] = 403
    assert (await model_client.get("/api/modelviewer/m2/1.m2")).status_code == 502


@pytest.mark.parametrize(
    "path",
    ["meta/../../js/tooltips.js", "meta/armor/5/8071.exe", "Meta/armor/5/8071.json", "8071.json", "m2/a.b.m2"],
)
async def test_only_viewer_files_are_relayed(model_client: AsyncTestClient, wowhead_state: dict, path: str) -> None:
    assert (await model_client.get(f"/api/modelviewer/{path}")).status_code == 404
    assert wowhead_state["requests"] == []
