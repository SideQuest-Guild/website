"""Battleground import (``SQX1:`` ``battlegrounds`` section) and the members-only ``/api/pvp/*`` routes.

See ``local://phase6-contract.md``.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from sidequest_common.models import BattlegroundMatch, BattlegroundScore, WowCharacter
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

RECORDER = "Officername-Whitemane"
EXPORTED_AT = 1793912345


def _export_string(payload: dict) -> str:
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"SQX1:{encoded}"


def _base_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "v": 2,
        "addon_version": "1.0.0",
        "exported_at": EXPORTED_AT,
        "guild": "SideQuest",
        "realm": "Whitemane",
        "recorder": RECORDER,
        "sessions": [],
        "encounters": [],
        "loot": [],
        "awards": [],
        "roster": None,
        "professions": [],
        "signups": [],
        "bank": [],
        "announcements": [],
        "recruits": [],
        "member_notes": [],
        "battlegrounds": [],
    }
    payload.update(overrides)
    return payload


def _match(
    *,
    match_id: str = "Zach-1793912345",
    ended_at: int = 1793912345,
    instance_id: int = 489,
    players: list[dict] | None = None,
    winner: str | None = "alliance",
    my_faction: str = "alliance",
    duration: int = 900,
    map_name: str = "Warsong Gulch",
) -> dict:
    return {
        "id": match_id,
        "map": map_name,
        "instance_id": instance_id,
        "ended_at": ended_at,
        "duration": duration,
        "winner": winner,
        "my_faction": my_faction,
        "players": players or [],
    }


def _player(
    name: str = "Zach", faction: str = "alliance", wow_class: str | None = "WARRIOR", **overrides: object
) -> dict:
    data: dict[str, object] = {
        "name": name,
        "faction": faction,
        "race": "Dwarf",
        "class": wow_class,
        "killing_blows": 3,
        "honorable_kills": 12,
        "deaths": 2,
        "honor_gained": 140,
        "damage_done": 45000,
        "healing_done": 1200,
    }
    data.update(overrides)
    return data


async def _login_officer(client: AsyncTestClient, discord_state: dict, *, discord_id: int = 100) -> None:
    response = await login_as(client, discord_state, discord_id=discord_id, roles=[OFFICER_ROLE_ID])
    assert response.status_code == 302, response.text


async def _seed_match(
    session: AsyncSession,
    *,
    external_id: str,
    ended_at: datetime,
    instance_id: int = 489,
    winner: str | None = "alliance",
    guild_faction: str = "alliance",
    recorder: str = RECORDER,
    map_name: str = "Warsong Gulch",
    duration: int = 900,
) -> BattlegroundMatch:
    match = BattlegroundMatch(
        external_id=external_id,
        map=map_name,
        instance_id=instance_id,
        ended_at=ended_at,
        duration=duration,
        winner=winner,
        guild_faction=guild_faction,
        recorder=recorder,
    )
    session.add(match)
    await session.flush()
    return match


def _score(
    match: BattlegroundMatch,
    *,
    name: str,
    faction: str = "alliance",
    character_id: object = None,
    wow_class: str | None = "warrior",
    killing_blows: int = 0,
    honorable_kills: int = 0,
    deaths: int = 0,
    honor_gained: int = 0,
    damage_done: int = 0,
    healing_done: int = 0,
) -> BattlegroundScore:
    return BattlegroundScore(
        match_id=match.id,
        character_id=character_id,
        name=name,
        faction=faction,
        race="Dwarf",
        wow_class=wow_class,
        killing_blows=killing_blows,
        honorable_kills=honorable_kills,
        deaths=deaths,
        honor_gained=honor_gained,
        damage_done=damage_done,
        healing_done=healing_done,
    )


# --- import: new, duplicate, merge --------------------------------------------------------------------------------


async def test_import_battleground_creates_match_and_scores(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8001)
    payload = _base_payload(battlegrounds=[_match(players=[_player()])])
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    assert response.json()["battlegrounds"] == {"new": 1, "merged": 0}
    async with db_sessionmaker() as session:
        match = (await session.execute(select(BattlegroundMatch))).scalar_one()
        assert match.external_id == "Zach-1793912345"
        assert match.map == "Warsong Gulch"
        assert match.recorder == RECORDER
        scores = (await session.execute(select(BattlegroundScore))).scalars().all()
        assert len(scores) == 1
        assert scores[0].name == "Zach"


async def test_import_battleground_is_idempotent_by_external_id(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8002)
    payload = _base_payload(battlegrounds=[_match(players=[_player()])])
    first = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert first.json()["battlegrounds"] == {"new": 1, "merged": 0}
    second = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert second.json()["battlegrounds"] == {"new": 0, "merged": 0}
    async with db_sessionmaker() as session:
        count = len((await session.execute(select(BattlegroundMatch))).scalars().all())
        assert count == 1


async def test_import_battleground_merges_another_members_recording_within_window(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8003)
    first_payload = _base_payload(
        battlegrounds=[_match(match_id="Zach-1793912345", ended_at=1793912345, players=[_player()])]
    )
    first = await member_client.post("/api/epgp/imports", json={"payload": _export_string(first_payload)})
    assert first.json()["battlegrounds"] == {"new": 1, "merged": 0}
    second_payload = _base_payload(
        battlegrounds=[_match(match_id="Other-1793912400", ended_at=1793912345 + 119, players=[_player(name="Other")])]
    )
    second = await member_client.post("/api/epgp/imports", json={"payload": _export_string(second_payload)})
    assert second.json()["battlegrounds"] == {"new": 0, "merged": 1}
    async with db_sessionmaker() as session:
        matches = (await session.execute(select(BattlegroundMatch))).scalars().all()
        assert len(matches) == 1
        scores = (await session.execute(select(BattlegroundScore))).scalars().all()
        assert len(scores) == 1  # the merged recording's scoreboard is not stored


async def test_import_battleground_is_new_outside_the_merge_window_or_different_instance(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8004)
    first_payload = _base_payload(
        battlegrounds=[_match(match_id="A-1", ended_at=1793912345, instance_id=489, players=[_player()])]
    )
    await member_client.post("/api/epgp/imports", json={"payload": _export_string(first_payload)})
    far_payload = _base_payload(
        battlegrounds=[
            _match(match_id="B-1", ended_at=1793912345 + 121, instance_id=489, players=[_player(name="Other")])
        ]
    )
    far = await member_client.post("/api/epgp/imports", json={"payload": _export_string(far_payload)})
    assert far.json()["battlegrounds"] == {"new": 1, "merged": 0}
    different_instance_payload = _base_payload(
        battlegrounds=[_match(match_id="C-1", ended_at=1793912345, instance_id=490, players=[_player(name="Third")])]
    )
    different = await member_client.post(
        "/api/epgp/imports", json={"payload": _export_string(different_instance_payload)}
    )
    assert different.json()["battlegrounds"] == {"new": 1, "merged": 0}
    async with db_sessionmaker() as session:
        count = len((await session.execute(select(BattlegroundMatch))).scalars().all())
        assert count == 3


# --- import: class mapping, character linking ---------------------------------------------------------------------


async def test_import_battleground_lowercases_valid_class_and_nulls_invalid(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8005)
    payload = _base_payload(
        battlegrounds=[
            _match(
                players=[
                    _player(name="Valid", wow_class="WARRIOR"),
                    _player(name="Invalid", wow_class="NOTACLASS"),
                    _player(name="Missing", wow_class=None),
                ]
            )
        ]
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    async with db_sessionmaker() as session:
        scores = {s.name: s for s in (await session.execute(select(BattlegroundScore))).scalars().all()}
        assert scores["Valid"].wow_class == "warrior"
        assert scores["Invalid"].wow_class is None
        assert scores["Missing"].wow_class is None


async def test_import_battleground_links_to_guild_character_by_casefolded_name(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8006)
    async with db_sessionmaker() as session:
        character = WowCharacter(name="Zach", realm="Whitemane", key="zach-whitemane", source="import")
        session.add(character)
        await session.commit()
        character_id = character.id
    payload = _base_payload(battlegrounds=[_match(players=[_player(name="zach")])])
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    async with db_sessionmaker() as session:
        score = (await session.execute(select(BattlegroundScore))).scalar_one()
        assert score.character_id == character_id


async def test_import_battleground_does_not_link_an_ambiguous_name(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8007)
    async with db_sessionmaker() as session:
        session.add_all(
            [
                WowCharacter(name="Dup", realm="Whitemane", key="dup-whitemane", source="import"),
                WowCharacter(name="Dup", realm="Other", key="dup-other", source="import"),
            ]
        )
        await session.commit()
    payload = _base_payload(battlegrounds=[_match(players=[_player(name="Dup")])])
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    async with db_sessionmaker() as session:
        score = (await session.execute(select(BattlegroundScore))).scalar_one()
        assert score.character_id is None


# --- routes: auth ---------------------------------------------------------------------------------------------


async def test_pvp_matches_requires_sign_in(member_client: AsyncTestClient) -> None:
    assert (await member_client.get("/api/pvp/matches")).status_code == 401


async def test_pvp_matches_requires_membership(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=8101, is_guild_member=False)
    assert (await member_client.get("/api/pvp/matches")).status_code == 403


async def test_pvp_boards_requires_sign_in(member_client: AsyncTestClient) -> None:
    assert (await member_client.get("/api/pvp/boards")).status_code == 401


async def test_pvp_match_detail_requires_sign_in(member_client: AsyncTestClient) -> None:
    assert (await member_client.get(f"/api/pvp/matches/{uuid4()}")).status_code == 401


# --- routes: paging, 404, match detail shape -----------------------------------------------------------------------


async def test_pvp_matches_pages_newest_first(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    async with db_sessionmaker() as session:
        for i in range(30):
            await _seed_match(session, external_id=f"m-{i}", ended_at=base + timedelta(minutes=i))
        await session.commit()
    await login_as(member_client, discord_state, discord_id=8102)
    first_page = await member_client.get("/api/pvp/matches", params={"page": 1})
    assert first_page.status_code == 200, first_page.text
    first_body = first_page.json()
    assert first_body["page"] == 1
    assert first_body["page_count"] == 2
    assert len(first_body["matches"]) == 25
    assert first_body["matches"][0]["ended_at"].startswith("2026-01-01T00:29")  # newest (i=29) first
    second_page = await member_client.get("/api/pvp/matches", params={"page": 2})
    second_body = second_page.json()
    assert len(second_body["matches"]) == 5


async def test_pvp_match_detail_404_for_unknown_id(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=8103)
    response = await member_client.get(f"/api/pvp/matches/{uuid4()}")
    assert response.status_code == 404


async def test_pvp_match_detail_includes_full_scoreboard_and_guild_players(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        character = WowCharacter(
            name="Zach", realm="Whitemane", key="zach-whitemane", source="import", slug="zach-whitemane"
        )
        session.add(character)
        await session.flush()
        match = await _seed_match(
            session,
            external_id="detail-1",
            ended_at=datetime(2026, 1, 1, tzinfo=UTC),
            winner="alliance",
            guild_faction="alliance",
        )
        session.add_all(
            [
                _score(match, name="Zach", faction="alliance", character_id=character.id, honorable_kills=20),
                _score(match, name="Enemy", faction="horde", honorable_kills=5),
            ]
        )
        await session.commit()
        match_id = match.id
    await login_as(member_client, discord_state, discord_id=8104)
    response = await member_client.get(f"/api/pvp/matches/{match_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["guild_players"] == ["Zach"]
    assert body["won"] is True
    assert [p["name"] for p in body["players"]] == ["Zach", "Enemy"]  # highest honorable kills first
    assert body["players"][0]["guild_member"] is True
    assert body["players"][0]["character_slug"] == "zach-whitemane"
    assert body["players"][1]["guild_member"] is False
    assert body["players"][1]["character_slug"] is None


# --- routes: boards math ---------------------------------------------------------------------------------------


async def test_pvp_boards_totals_guild_linked_rows_across_matches(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        char_a = WowCharacter(
            name="CharA", realm="Whitemane", key="chara-whitemane", source="import", wow_class="warrior"
        )
        char_b = WowCharacter(name="CharB", realm="Whitemane", key="charb-whitemane", source="import", wow_class="mage")
        session.add_all([char_a, char_b])
        await session.flush()

        match1 = await _seed_match(
            session,
            external_id="board-1",
            ended_at=datetime(2026, 1, 1, tzinfo=UTC),
            instance_id=489,
            winner="alliance",
            guild_faction="alliance",
        )
        session.add_all(
            [
                _score(
                    match1,
                    name="CharA",
                    faction="alliance",
                    character_id=char_a.id,
                    honorable_kills=50,
                    killing_blows=5,
                    honor_gained=100,
                    damage_done=1000,
                ),
                _score(
                    match1,
                    name="CharB",
                    faction="horde",
                    character_id=char_b.id,
                    honorable_kills=10,
                    killing_blows=2,
                    honor_gained=20,
                    damage_done=500,
                ),
            ]
        )

        match2 = await _seed_match(
            session,
            external_id="board-2",
            ended_at=datetime(2026, 1, 2, tzinfo=UTC),
            instance_id=490,
            winner="horde",
            guild_faction="horde",
        )
        session.add_all(
            [
                _score(
                    match2,
                    name="CharA",
                    faction="alliance",
                    character_id=char_a.id,
                    honorable_kills=5,
                    killing_blows=1,
                    honor_gained=10,
                    damage_done=100,
                ),
                _score(
                    match2,
                    name="CharB",
                    faction="horde",
                    character_id=char_b.id,
                    honorable_kills=20,
                    killing_blows=3,
                    honor_gained=30,
                    damage_done=200,
                ),
            ]
        )
        await session.commit()

    await login_as(member_client, discord_state, discord_id=8105)
    response = await member_client.get("/api/pvp/boards")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["matches"] == 2
    assert [entry["name"] for entry in body["honorable_kills"]] == ["CharA", "CharB"]
    assert body["honorable_kills"][0]["value"] == 55
    assert body["honorable_kills"][1]["value"] == 30
    wins_by_name = {entry["name"]: entry["value"] for entry in body["wins"]}
    assert wins_by_name == {"CharA": 1, "CharB": 1}
    assert [entry["name"] for entry in body["damage_done"]] == ["CharA", "CharB"]
    assert body["damage_done"][0]["value"] == 1100
    assert body["damage_done"][1]["value"] == 700
