"""``/api/quests`` and ``/api/achievements``: quest and achievement reference lookups, against a fake Battle.net."""

from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient

from sidequest_api.app import create_app
from sidequest_api.domain.reference import services as reference_services
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import TEST_API_KEY
from tests.unit.api.fake_battlenet import API, PATCH, battlenet, forget_battlenet_state, transport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name


def _ref(kind: str, ref_id: int, name: str) -> dict:
    return {"id": ref_id, "name": name, "key": {"href": f"{API}/data/wow/{kind}/{ref_id}?namespace={PATCH}"}}


def _links(path: str) -> dict:
    return {"_links": {"self": {"href": f"{API}{path}?namespace={PATCH}"}}}


@pytest.fixture(autouse=True)
def _forget_reference_caches() -> None:
    """The reference lookups' caches are process-wide; tests must not see each other's."""
    reference_services._quest_area_index = None
    reference_services._quest_areas.clear()
    reference_services._quests.clear()
    reference_services._raw_quests.clear()
    reference_services._quest_chains.clear()
    reference_services._quest_leads_to_cache.clear()
    reference_services._quest_title_index = None
    reference_services._achievement_category_tree = None
    reference_services._achievement_categories.clear()
    reference_services._achievements.clear()


@pytest.fixture
async def reference_client(database_url: str, battlenet: dict) -> AsyncIterator[AsyncTestClient[Litestar]]:
    settings = WebSettings(_env_file=None, BATTLENET_CLIENT_ID="bnet-id", BATTLENET_CLIENT_SECRET="bnet-secret")

    battlenet["documents"].update(
        {
            "/data/wow/quest/area/index": {
                **_links("/data/wow/quest/area/index"),
                "areas": [_ref("quest/area", 15, "Dustwallow Marsh"), _ref("quest/area", 1, "Dun Morogh")],
            },
            "/data/wow/quest/area/15": {
                **_links("/data/wow/quest/area/15"),
                "id": 15,
                "area": "Dustwallow Marsh",
                "quests": [_ref("quest", 1, "The Missing Diplomat"), _ref("quest", 2, "Buzzbox 411")],
            },
            "/data/wow/quest/1": {
                **_links("/data/wow/quest/1"),
                "id": 1,
                "title": "The Missing Diplomat",
                "description": "Find the diplomat, {class}.",
                "area": _ref("quest/area", 15, "Dustwallow Marsh"),
                "category": _ref("quest/category", 10, "Epic"),
                "type": _ref("quest/type", 1, "Elite"),
                "requirements": {"min_character_level": 20, "max_character_level": 60},
                "rewards": {
                    "experience": 550,
                    "items": {
                        "items": [
                            {"item": _ref("item", 159, "Refreshing Spring Water")},
                            {"item": _ref("item", 118, "Minor Healing Potion")},
                        ]
                    },
                    "money": {"units": {"gold": 0, "silver": 2, "copper": 25}, "value": 225},
                    "reputations": [{"reward": _ref("reputation-faction", 529, "Argent Dawn"), "value": 75}],
                },
                "is_repeatable": True,
                "is_daily": False,
            },
            "/data/wow/quest/area/1": {
                **_links("/data/wow/quest/area/1"),
                "id": 1,
                "area": "Dun Morogh",
                "quests": [
                    _ref("quest", 50, "Rage Scar Hold"),
                    _ref("quest", 60, "Call of Water"),
                    _ref("quest", 61, "Call of Water II"),
                    _ref("quest", 62, "The Call"),
                ],
            },
            "/data/wow/quest/area/99": {
                **_links("/data/wow/quest/area/99"),
                "id": 99,
                "area": "Follow-up Zone",
                "quests": [_ref("quest", 201, "Starting Point"), _ref("quest", 202, "The Sequel")],
            },
            "/data/wow/quest/category/index": {
                **_links("/data/wow/quest/category/index"),
                "categories": [_ref("quest/category", 82, "Shaman"), _ref("quest/category", 83, "Gone")],
            },
            "/data/wow/quest/category/82": {
                **_links("/data/wow/quest/category/82"),
                "id": 82,
                "category": "Shaman",
                "quests": [_ref("quest", 60, "Call of Water"), _ref("quest", 400, "Call of the Earth")],
            },
            "/data/wow/quest/201": {
                **_links("/data/wow/quest/201"),
                "id": 201,
                "title": "Starting Point",
                "area": _ref("quest/area", 99, "Follow-up Zone"),
                "requirements": {},
                "rewards": {},
            },
            "/data/wow/quest/202": {
                **_links("/data/wow/quest/202"),
                "id": 202,
                "title": "The Sequel",
                "area": _ref("quest/area", 99, "Follow-up Zone"),
                "requirements": {"quests": {"target": _ref("quest", 201, "Starting Point")}},
                "rewards": {},
            },
            "/data/wow/quest/301": {
                **_links("/data/wow/quest/301"),
                "id": 301,
                "title": "Gear Up",
                "requirements": {},
                "rewards": {},
            },
            "/data/wow/quest/310": {
                **_links("/data/wow/quest/310"),
                "id": 310,
                "title": "Final Stand",
                "requirements": {
                    "quests": {
                        "operator": {"type": "AND", "name": "And"},
                        "conditions": [
                            {
                                "operator": {"type": "OR", "name": "Or"},
                                "conditions": [
                                    {"target": _ref("quest", 311, "Path A"), "must_be_incomplete": True},
                                    {"target": _ref("quest", 312, "Path B"), "must_be_incomplete": True},
                                ],
                            },
                            {"target": _ref("quest", 301, "Gear Up")},
                        ],
                    }
                },
                "rewards": {},
            },
            "/data/wow/quest/321": {
                **_links("/data/wow/quest/321"),
                "id": 321,
                "title": "Scout the Camp",
                "requirements": {},
                "rewards": {},
            },
            "/data/wow/quest/320": {
                **_links("/data/wow/quest/320"),
                "id": 320,
                "title": "Either Path",
                "requirements": {
                    "quests": {
                        "operator": {"type": "OR", "name": "Or"},
                        "conditions": [
                            {"target": _ref("quest", 321, "Scout the Camp")},
                            {"target": _ref("quest", 322, "Storm the Gate")},
                        ],
                    }
                },
                "rewards": {},
            },
            "/data/wow/quest/330": {
                **_links("/data/wow/quest/330"),
                "id": 330,
                "title": "Loop A",
                "requirements": {"quests": {"target": _ref("quest", 331, "Loop B")}},
                "rewards": {},
            },
            "/data/wow/quest/331": {
                **_links("/data/wow/quest/331"),
                "id": 331,
                "title": "Loop B",
                "requirements": {"quests": {"target": _ref("quest", 330, "Loop A")}},
                "rewards": {},
            },
            "/data/wow/achievement-category/index": {
                **_links("/data/wow/achievement-category/index"),
                "categories": [_ref("achievement-category", 15587, "Alchemy")],
                "root_categories": [
                    _ref("achievement-category", 15425, "Do Not Display"),
                    _ref("achievement-category", 15568, "Classes"),
                    _ref("achievement-category", 15586, "Tradeskills"),
                ],
            },
            "/data/wow/achievement-category/15425": {
                **_links("/data/wow/achievement-category/15425"),
                "id": 15425,
                "name": "Do Not Display",
                "display_order": 0,
                "is_guild_category": False,
            },
            "/data/wow/achievement-category/15568": {
                **_links("/data/wow/achievement-category/15568"),
                "id": 15568,
                "name": "Classes",
                "display_order": 3,
                "is_guild_category": False,
                "subcategories": [_ref("achievement-category", 15587, "Alchemy")],
            },
            "/data/wow/achievement-category/15586": {
                **_links("/data/wow/achievement-category/15586"),
                "id": 15586,
                "name": "Tradeskills",
                "display_order": 2,
                "is_guild_category": False,
            },
            "/data/wow/achievement-category/15587": {
                **_links("/data/wow/achievement-category/15587"),
                "id": 15587,
                "name": "Alchemy",
                "display_order": 1,
                "is_guild_category": False,
                "parent_category": _ref("achievement-category", 15586, "Tradeskills"),
                "achievements": [_ref("achievement", 62012, "Journeyman Alchemist")],
            },
            "/data/wow/achievement/62012": {
                **_links("/data/wow/achievement/62012"),
                "id": 62012,
                "name": "Journeyman Alchemist",
                "description": "Learn 150 alchemy recipes.",
                "points": 10,
                "is_account_wide": False,
                "display_order": 1,
                "category": _ref("achievement-category", 15587, "Alchemy"),
                "media": {"id": 62012, "key": {"href": f"{API}/data/wow/media/achievement/62012?namespace={PATCH}"}},
                "criteria": {"id": 1, "description": None, "amount": 0, "child_criteria": []},
            },
            "/data/wow/achievement/728": {
                **_links("/data/wow/achievement/728"),
                "id": 728,
                "name": "Explore Durotar",
                "description": "Explore Durotar, revealing the covered areas of the world map.",
                "points": 10,
                "is_account_wide": False,
                "display_order": 6,
                "reward_description": "A sense of accomplishment.",
                "category": _ref("achievement-category", 14778, "Kalimdor"),
                "media": {"id": 728, "key": {"href": f"{API}/data/wow/media/achievement/728?namespace={PATCH}"}},
                "criteria": {
                    "id": 126894,
                    "description": None,
                    "amount": 0,
                    "operator": {"type": "AND", "name": "All"},
                    "child_criteria": [
                        {"id": 1, "description": "Explore Razor Hill", "amount": 0, "child_criteria": []},
                        {"id": 2, "description": "Explore the Valley of Trials", "amount": 0, "child_criteria": []},
                    ],
                },
            },
            "/data/wow/media/achievement/728": {
                **_links("/data/wow/media/achievement/728"),
                "id": 728,
                "assets": [
                    {
                        "key": "icon",
                        "value": "https://render.worldofwarcraft.com/forever-us/icons/56/achievement_728.jpg",
                        "file_data_id": 1,
                    }
                ],
            },
        }
    )
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        settings,
        game_data_transport=transport(battlenet),
    )
    async with AsyncTestClient(app=app) as client:
        yield client


async def test_quest_areas_lists_every_zone(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/quests/areas")

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "name": "Dun Morogh"}, {"id": 15, "name": "Dustwallow Marsh"}]


async def test_a_quest_area_lists_its_quests(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/quests/areas/15")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 15
    assert body["name"] == "Dustwallow Marsh"
    assert body["quests"] == [{"id": 1, "title": "The Missing Diplomat"}, {"id": 2, "title": "Buzzbox 411"}]


async def test_an_unknown_quest_area_is_not_found(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/quests/areas/999999")

    assert response.status_code == 404


async def test_a_quest_carries_its_description_requirements_and_rewards(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/quests/1")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "The Missing Diplomat"
    assert body["description"] == "Find the diplomat, adventurer."  # the game fills {class} in with the reader's
    assert body["area"] == "Dustwallow Marsh"
    assert body["category"] == "Epic"
    assert body["type"] == "Elite"
    assert body["min_level"] == 20
    assert body["max_level"] == 60
    assert body["is_repeatable"] is True
    assert body["is_daily"] is False
    assert body["rewards"] == {
        "experience": 550,
        "money": 25,
        "items": [
            {"item_id": 159, "name": "Refreshing Spring Water"},
            {"item_id": 118, "name": "Minor Healing Potion"},
        ],
        "reputations": [{"faction": "Argent Dawn", "value": 75}],
    }


async def test_an_unknown_quest_is_not_found(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/quests/999999999")

    assert response.status_code == 404


async def test_a_quest_is_fetched_once_then_served_from_cache(
    reference_client: AsyncTestClient, battlenet: dict
) -> None:
    await reference_client.get("/api/quests/1")
    await reference_client.get("/api/quests/1")

    quest_requests = [r for r in battlenet["requests"] if r.url.path == "/data/wow/quest/1"]
    assert len(quest_requests) == 1


async def test_quests_answer_503_when_battlenet_is_not_configured(client: AsyncTestClient) -> None:
    assert (await client.get("/api/quests/areas")).status_code == 503
    assert (await client.get("/api/quests/areas/15")).status_code == 503
    assert (await client.get("/api/quests/1")).status_code == 503
    assert (await client.get("/api/quests/search", params={"q": "call"})).status_code == 503


async def test_a_quests_requirements_flatten_nested_and_and_an_or_lockout(
    reference_client: AsyncTestClient,
) -> None:
    response = await reference_client.get("/api/quests/310")

    assert response.status_code == 200
    body = response.json()
    assert body["requires"] == [{"id": 301, "title": "Gear Up", "group": None}]
    assert body["excludes"] == [{"id": 311, "title": "Path A"}, {"id": 312, "title": "Path B"}]
    assert body["chain"] == [{"id": 301, "title": "Gear Up"}]


async def test_an_or_requirement_groups_its_alternatives(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/quests/320")

    assert response.status_code == 200
    body = response.json()
    assert body["requires"] == [
        {"id": 321, "title": "Scout the Camp", "group": 0},
        {"id": 322, "title": "Storm the Gate", "group": 0},
    ]
    assert body["excludes"] == []


async def test_a_quest_chain_walks_back_through_its_first_required_prerequisite(
    reference_client: AsyncTestClient,
) -> None:
    response = await reference_client.get("/api/quests/202")

    assert response.status_code == 200
    body = response.json()
    assert body["chain"] == [{"id": 201, "title": "Starting Point"}]
    assert body["requires"] == [{"id": 201, "title": "Starting Point", "group": None}]


async def test_a_quest_chain_stops_at_a_cycle_instead_of_looping_forever(
    reference_client: AsyncTestClient,
) -> None:
    response = await reference_client.get("/api/quests/330")

    assert response.status_code == 200
    assert response.json()["chain"] == [{"id": 331, "title": "Loop B"}]


async def test_leads_to_finds_a_follow_up_quest_in_the_same_zone(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/quests/201")

    assert response.status_code == 200
    assert response.json()["leads_to"] == [{"id": 202, "title": "The Sequel"}]


async def test_quest_search_ranks_exact_and_prefix_matches_before_other_substrings(
    reference_client: AsyncTestClient,
) -> None:
    response = await reference_client.get("/api/quests/search", params={"q": "call of water"})

    assert response.status_code == 200
    assert response.json() == [
        {"id": 60, "title": "Call of Water", "area": "Dun Morogh"},
        {"id": 61, "title": "Call of Water II", "area": "Dun Morogh"},
    ]


async def test_quest_search_is_case_insensitive(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/quests/search", params={"q": "DIPLOMAT"})

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "title": "The Missing Diplomat", "area": "Dustwallow Marsh"}]


async def test_quest_search_respects_the_limit(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/quests/search", params={"q": "call", "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [60, 61]


async def test_quest_search_finds_nothing_for_an_unmatched_query(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/quests/search", params={"q": "nonexistent"})

    assert response.status_code == 200
    assert response.json() == []


async def test_quest_search_finds_quests_only_a_category_lists_and_keeps_a_zone_over_a_category(
    reference_client: AsyncTestClient,
) -> None:
    """Class quests have no zone; the category (Shaman) stands in, and a quest a zone also lists keeps its zone."""
    response = await reference_client.get("/api/quests/search", params={"q": "call of"})

    assert response.status_code == 200
    assert response.json() == [
        {"id": 60, "title": "Call of Water", "area": "Dun Morogh"},
        {"id": 61, "title": "Call of Water II", "area": "Dun Morogh"},
        {"id": 400, "title": "Call of the Earth", "area": "Shaman"},
    ]


async def test_achievement_categories_lists_root_categories_with_their_children_but_not_blizzards_hidden_one(
    reference_client: AsyncTestClient,
) -> None:
    response = await reference_client.get("/api/achievements/categories")

    assert response.status_code == 200
    body = response.json()
    assert body == [
        {"id": 15586, "name": "Tradeskills", "children": []},
        {"id": 15568, "name": "Classes", "children": [{"id": 15587, "name": "Alchemy"}]},
    ]


async def test_an_achievement_category_lists_its_achievements_with_points(
    reference_client: AsyncTestClient,
) -> None:
    response = await reference_client.get("/api/achievements/categories/15587")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 15587
    assert body["name"] == "Alchemy"
    assert body["achievements"] == [{"id": 62012, "name": "Journeyman Alchemist", "points": 10, "icon_url": None}]


async def test_an_unknown_achievement_category_is_not_found(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/achievements/categories/999999")

    assert response.status_code == 404


async def test_an_achievement_carries_its_icon_and_criteria_tree(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/achievements/728")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Explore Durotar"
    assert body["description"] == "Explore Durotar, revealing the covered areas of the world map."
    assert body["points"] == 10
    assert body["category"] == "Kalimdor"
    assert body["reward_description"] == "A sense of accomplishment."
    assert body["icon_url"] == "https://render.worldofwarcraft.com/forever-us/icons/56/achievement_728.jpg"
    assert body["criteria"] == {
        "description": None,
        "amount": 0,
        "children": [
            {"description": "Explore Razor Hill", "amount": 0, "children": []},
            {"description": "Explore the Valley of Trials", "amount": 0, "children": []},
        ],
    }


async def test_an_unknown_achievement_is_not_found(reference_client: AsyncTestClient) -> None:
    response = await reference_client.get("/api/achievements/999999999")

    assert response.status_code == 404


async def test_browsing_a_category_first_saves_a_request_on_the_achievement_page(
    reference_client: AsyncTestClient, battlenet: dict
) -> None:
    await reference_client.get("/api/achievements/categories/15587")
    requests_after_category = len(battlenet["requests"])
    response = await reference_client.get("/api/achievements/62012")

    assert response.status_code == 200
    assert response.json()["points"] == 10
    new_requests = battlenet["requests"][requests_after_category:]
    # Only the icon's media request, not the achievement document again (shared with the category's cache).
    assert [r.url.path for r in new_requests] == ["/data/wow/media/achievement/62012"]


async def test_achievements_answer_503_when_battlenet_is_not_configured(client: AsyncTestClient) -> None:
    assert (await client.get("/api/achievements/categories")).status_code == 503
    assert (await client.get("/api/achievements/categories/15587")).status_code == 503
    assert (await client.get("/api/achievements/728")).status_code == 503
