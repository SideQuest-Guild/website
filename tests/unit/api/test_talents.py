"""The talent calculator: ``GET /api/talents/{wow_class}``, saved builds, pinning, and account deletion.

Most tests use a small, hand-built Warrior tree: three identical four-row trees (Arms 26, Fury 256, Protection
257) under class tree 1117, each with two rank-9 nodes on rows 1 and 2, then a rank-1 node on row 3 that requires
the row-2 node at max rank, then a rank-1 capstone on row 4 that requires the row-3 node. That exercises every
validation rule (max rank, prerequisites, row gating, the point cap: three full trees total 60, over the 51 cap).
One test reads Battle.net's real Druid documents (``fixtures/battlenet/static/talent-tree/``), whose links carry a
``?namespace=`` query and whose prerequisite pairs point at each other.
"""

from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import select

from sidequest_api.app import create_app
from sidequest_common.models import Member, TalentBuild
from sidequest_common.schemas import MAX_TALENT_BUILDS
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import TEST_API_KEY
from tests.unit.api.conftest import OFFICER_ROLE_ID, _discord_transport, login_as
from tests.unit.api.fake_battlenet import battlenet, forget_battlenet_state, recorded_document, transport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name

TREE_ID = 1117
SPECS = [(26, "Arms"), (256, "Fury"), (257, "Protection")]
TALENTS = "/api/talents"
BUILDS = "/api/talent-builds"
MY_BUILDS = "/api/me/talent-builds"

# A full build spends every point this tree offers: 9 + 9 + 1 + 1 = 20, times 3 trees = 60 (over the 51 cap).
FULL_SEGMENT = "9911"


def _ref(kind: str, ref_id: int, name: str) -> dict:
    return {"key": {"href": f"https://us.api.blizzard.com/data/wow/{kind}/{ref_id}"}, "id": ref_id, "name": name}


def _node(node_id: int, row: int, col: int, max_rank: int, *, locked_by: tuple[int, ...] = ()) -> dict:
    talent = _ref("talent", node_id, f"Node {node_id}")
    spell = _ref("spell", node_id * 10, f"Spell {node_id}")
    return {
        "id": node_id,
        "display_row": row,
        "display_col": col,
        "raw_position_x": col * 100,
        "raw_position_y": row * 100,
        "node_type": {"id": 0, "type": "ACTIVE"},
        "ranks": [
            {
                "rank": rank,
                "tooltip": {
                    "talent": talent,
                    "spell_tooltip": {
                        "cast_time": "Passive",
                        "description": f"Rank {rank} of node {node_id}.",
                        "spell": spell,
                    },
                },
            }
            for rank in range(1, max_rank + 1)
        ],
        "locked_by": list(locked_by),
        "unlocks": [],
    }


def _tree_document(spec_id: int, spec_name: str) -> dict:
    base = spec_id * 1000
    row1, row2, row3, row4 = base + 1, base + 2, base + 3, base + 4
    return {
        "_links": {"self": {"href": f"https://us.api.blizzard.com/data/wow/talent-tree/{TREE_ID}"}},
        "id": TREE_ID,
        "name": spec_name,
        "media": {"key": {"href": f"https://us.api.blizzard.com/data/wow/media/talent-tree/{TREE_ID}"}},
        "playable_class": _ref("playable-class", 1, "Warrior"),
        "playable_specialization": _ref("playable-specialization", spec_id, spec_name),
        "spec_talent_nodes": [
            _node(row1, 1, 1, 9),
            _node(row2, 2, 1, 9, locked_by=()),
            _node(row3, 3, 1, 1, locked_by=(row2,)),
            _node(row4, 4, 1, 1, locked_by=(row3,)),
        ],
    }


def seed_talent_documents(battlenet: dict) -> None:
    """Loads the Warrior fixture trees into the fake Battle.net's ``documents`` map."""
    battlenet["documents"]["/data/wow/talent-tree/index"] = {
        "_links": {"self": {"href": "https://us.api.blizzard.com/data/wow/talent-tree/"}},
        "class_talent_trees": [
            {"key": {"href": f"https://us.api.blizzard.com/data/wow/talent-tree/{TREE_ID}"}, "name": "Warrior"}
        ],
        "spec_talent_trees": [
            {
                "key": {
                    "href": f"https://us.api.blizzard.com/data/wow/talent-tree/{TREE_ID}/playable-specialization/{spec_id}"
                },
                "name": name,
            }
            for spec_id, name in SPECS
        ],
    }
    for spec_id, name in SPECS:
        battlenet["documents"][f"/data/wow/talent-tree/{TREE_ID}/playable-specialization/{spec_id}"] = _tree_document(
            spec_id, name
        )
        battlenet["documents"][f"/data/wow/media/playable-specialization/{spec_id}"] = {
            "_links": {
                "self": {"href": f"https://us.api.blizzard.com/data/wow/media/playable-specialization/{spec_id}"}
            },
            "id": spec_id,
            "assets": [
                {
                    "key": "icon",
                    "value": f"https://render.worldofwarcraft.com/icons/56/spec-{spec_id}.jpg",
                    "file_data_id": spec_id,
                }
            ],
        }


@pytest.fixture
async def talents_client(
    database_url: str, member_web_settings: WebSettings, discord_state: dict, battlenet: dict
) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Member sign-in plus the fake Battle.net, seeded with the small Warrior fixture tree."""
    seed_talent_documents(battlenet)
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        member_web_settings,
        discord_transport=_discord_transport(discord_state),
        game_data_transport=transport(battlenet),
    )
    async with AsyncTestClient(app=app) as client:
        yield client


async def test_the_class_talents_endpoint_returns_three_trees_and_is_cached_after_the_first_call(
    talents_client: AsyncTestClient, battlenet: dict
) -> None:
    first = await talents_client.get(f"{TALENTS}/warrior")
    second = await talents_client.get(f"{TALENTS}/warrior")

    assert first.status_code == 200
    body = first.json()
    assert body["class"] == "warrior"
    assert body["max_points"] == 51
    assert body["first_level"] == 10
    assert [tree["name"] for tree in body["trees"]] == ["Arms", "Fury", "Protection"]
    first_tree = body["trees"][0]
    assert len(first_tree["nodes"]) == 4
    assert first_tree["icon_url"] == "https://render.worldofwarcraft.com/icons/56/spec-26.jpg"
    node = first_tree["nodes"][0]
    assert (node["row"], node["col"], node["max_rank"]) == (1, 1, 9)
    assert len(node["ranks"]) == 9
    assert node["requires"] is None
    prereq_node = first_tree["nodes"][2]
    assert prereq_node["requires"] == first_tree["nodes"][1]["id"]

    # The second call is answered from the in-process cache: no more tree requests went out.
    tree_requests = [r for r in battlenet["requests"] if "/talent-tree/" in r.url.path and "index" not in r.url.path]
    assert len(tree_requests) == 3
    assert second.status_code == 200


async def test_an_unknown_class_404s(talents_client: AsyncTestClient) -> None:
    response = await talents_client.get(f"{TALENTS}/monk")
    assert response.status_code == 400  # not a WowClass value at all


async def test_the_real_druid_trees_load_with_one_way_prerequisites(
    talents_client: AsyncTestClient, battlenet: dict
) -> None:
    battlenet["documents"]["/data/wow/talent-tree/index"] = recorded_document("static/talent-tree/index")
    for spec_id in (574, 134, 573):
        path = f"talent-tree/1089/playable-specialization/{spec_id}"
        battlenet["documents"][f"/data/wow/{path}"] = recorded_document(f"static/{path}")

    response = await talents_client.get(f"{TALENTS}/druid")

    assert response.status_code == 200
    trees = response.json()["trees"]
    assert [tree["name"] for tree in trees] == ["Balance", "Feral Combat", "Restoration"]
    balance = {node["name"]: node for node in trees[0]["nodes"]}
    # Battle.net lists Nature's Majesty and Nature's Splendor in each other's locked_by: the row-2 talent comes first.
    assert balance["Nature's Majesty"]["requires"] is None
    assert balance["Nature's Splendor"]["requires"] == balance["Nature's Majesty"]["id"]
    assert balance["Vengeance"]["requires"] == balance["Improved Moonfire"]["id"]
    # Battle.net numbers columns across the class window (Feral 7-10, Restoration 14-17); each tree's grid is 1-4.
    assert [sorted({node["col"] for node in tree["nodes"]}) for tree in trees] == [[1, 2, 3, 4]] * 3


async def test_stray_copies_battle_net_places_outside_the_tree_are_left_out(
    talents_client: AsyncTestClient, battlenet: dict
) -> None:
    # Shapes from the live Hunter and Priest data: a tree at columns 14-17 with a duplicate parked at column 170 on
    # the last row, and another copy at row 33.
    path = f"/data/wow/talent-tree/{TREE_ID}/playable-specialization/{SPECS[0][0]}"
    document = battlenet["documents"][path]
    document["spec_talent_nodes"] = [
        _node(1, 1, 14, 5),
        _node(2, 1, 17, 5),
        _node(3, 7, 15, 1),
        _node(4, 7, 170, 5),
        _node(5, 33, 14, 5),
    ]

    response = await talents_client.get(f"{TALENTS}/warrior")

    nodes = response.json()["trees"][0]["nodes"]
    assert [(node["id"], node["row"], node["col"]) for node in nodes] == [(1, 1, 1), (2, 1, 4), (3, 7, 2)]


async def test_a_member_saves_a_build_and_can_delete_only_their_own(
    talents_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(talents_client, discord_state, discord_id=8001)

    created = await talents_client.post(
        MY_BUILDS, json={"class": "warrior", "name": "Arms leveling", "code": f"{FULL_SEGMENT}-0-0", "note": "solo"}
    )

    assert created.status_code == 201
    build = created.json()
    assert (build["class"], build["name"], build["code"], build["note"], build["pinned"]) == (
        "warrior",
        "Arms leveling",
        f"{FULL_SEGMENT}-0-0",
        "solo",
        False,
    )

    mine = await talents_client.get(MY_BUILDS)
    assert [row["id"] for row in mine.json()] == [build["id"]]

    await login_as(talents_client, discord_state, discord_id=8002, username="other")
    not_owner = await talents_client.delete(f"{MY_BUILDS}/{build['id']}")
    assert not_owner.status_code == 404

    await login_as(talents_client, discord_state, discord_id=8001)
    owner_delete = await talents_client.delete(f"{MY_BUILDS}/{build['id']}")
    missing_again = await talents_client.delete(f"{MY_BUILDS}/{build['id']}")
    assert (owner_delete.status_code, missing_again.status_code) == (204, 404)


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("0020-0-0", "only has 1 ranks"),  # rank above a node's max (checked before row gating)
        ("0-0-0-0", "tree segments"),  # wrong number of tree segments
        ("00000-0-0", "doesn't have that many talent nodes"),  # more digits than nodes
        ("9010-0-0", "isn't open yet"),  # row 3 point without 10 points spent in rows before it
        ("9510-0-0", "needs"),  # row-3 node without its prerequisite (row 2) maxed
    ],
)
async def test_an_invalid_build_code_is_refused_with_a_reason(
    talents_client: AsyncTestClient, discord_state: dict, code: str, reason: str
) -> None:
    await login_as(talents_client, discord_state, discord_id=8003)

    response = await talents_client.post(MY_BUILDS, json={"class": "warrior", "name": "Bad", "code": code})

    assert response.status_code == 400
    assert reason in response.json()["detail"]


async def test_a_build_spending_more_than_the_point_cap_is_refused(
    talents_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(talents_client, discord_state, discord_id=8004)

    under_cap = await talents_client.post(
        MY_BUILDS, json={"class": "warrior", "name": "One tree full", "code": f"{FULL_SEGMENT}-0-0"}
    )
    assert under_cap.status_code == 201

    over_cap = await talents_client.post(
        MY_BUILDS,
        json={"class": "warrior", "name": "Everything", "code": "-".join([FULL_SEGMENT] * 3)},
    )
    assert over_cap.status_code == 400
    assert "51 points" in over_cap.json()["detail"]


async def test_a_full_build_list_refuses_another_save(
    talents_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(talents_client, discord_state, discord_id=8005)
    async with db_sessionmaker() as session:
        member = (await session.execute(select(Member).where(Member.discord_id == 8005))).scalar_one()
        session.add_all(
            TalentBuild(member_id=member.id, wow_class="warrior", name=f"Build {n}", code="0-0-0")
            for n in range(MAX_TALENT_BUILDS)
        )
        await session.commit()

    response = await talents_client.post(MY_BUILDS, json={"class": "warrior", "name": "One too many", "code": "0-0-0"})

    assert response.status_code == 409


async def test_only_an_officer_can_pin_a_build(talents_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(talents_client, discord_state, discord_id=8006, username="wants-to-pin")
    created = await talents_client.post(MY_BUILDS, json={"class": "warrior", "name": "Raid build", "code": "0-0-0"})
    build_id = created.json()["id"]

    forbidden = await talents_client.put(f"{BUILDS}/{build_id}/pin", json={"pinned": True})
    assert forbidden.status_code == 403

    await login_as(talents_client, discord_state, discord_id=8007, username="officer", roles=[OFFICER_ROLE_ID])
    pinned = await talents_client.put(f"{BUILDS}/{build_id}/pin", json={"pinned": True})
    assert pinned.status_code == 200
    assert pinned.json()["pinned"] is True

    public = await talents_client.get(f"{BUILDS}?class=warrior")
    assert [row["id"] for row in public.json()] == [build_id]
    assert public.json()[0]["member_name"] == "wants-to-pin"

    unpinned = await talents_client.put(f"{BUILDS}/{build_id}/pin", json={"pinned": False})
    assert unpinned.status_code == 200
    assert (await talents_client.get(f"{BUILDS}?class=warrior")).json() == []


async def test_deleting_an_account_deletes_its_talent_builds(
    talents_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(talents_client, discord_state, discord_id=8008)
    await talents_client.post(MY_BUILDS, json={"class": "warrior", "name": "Mine", "code": "0-0-0"})

    response = await talents_client.delete("/api/me")

    assert response.status_code == 204
    async with db_sessionmaker() as session:
        assert (await session.execute(select(TalentBuild))).scalars().all() == []
