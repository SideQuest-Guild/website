"""Characters from Battle.net: the bot's roster sync, character pages, search, hero boards and raid readiness."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import select, update

from sidequest_api.app import create_app
from sidequest_common.models import BattlenetCharacter, GuildEvent, GuildRecruit, WowCharacter
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import GUILD_ID, TEST_API_KEY
from tests.unit.api.conftest import OFFICER_ROLE_ID, _discord_transport, login_as
from tests.unit.api.fake_battlenet import TERRORSKULL, battlenet, forget_battlenet_state, roster_member, transport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name

SYNC = f"/api/guilds/{GUILD_ID}/characters/sync"
BOT = {"X-API-Key": TEST_API_KEY}


@pytest.fixture
async def characters_client(
    database_url: str, member_web_settings: WebSettings, discord_state: dict, battlenet: dict
) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Member sign-in, the bot key and the fake Battle.net, whose roster also has Terrorskull Gloomstep (rank 2)."""
    battlenet["roster"].append(roster_member("Terrorskull", "Gloomstep", rank=2, level=12))
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        member_web_settings,
        discord_transport=_discord_transport(discord_state),
        game_data_transport=transport(battlenet),
    )
    async with AsyncTestClient(app=app) as client:
        yield client


def _profile_requests(battlenet: dict) -> int:
    return sum(request.url.path.startswith("/profile/") for request in battlenet["requests"])


async def test_the_roster_sync_stores_every_member_and_the_published_profiles(
    characters_client: AsyncTestClient,
) -> None:
    report = await characters_client.post(SYNC, headers=BOT)

    assert report.status_code == 200
    # The first sync has no earlier roster to compare against, so it reports nobody as joined.
    assert report.json() == {
        "members": 8,
        "joined": [],
        "left": [],
        "profiles_refreshed": 1,
        "characters_linked": 0,
    }
    roster = (await characters_client.get("/api/characters/")).json()
    assert [(row["name"], row["guild_rank"]) for row in roster][:3] == [("Zach", 0), ("Legs", 1), ("Terrorskull", 2)]
    by_slug = {row["slug"]: row for row in roster}
    terrorskull = by_slug[TERRORSKULL]
    assert (terrorskull["profile_found"], terrorskull["level"]) == (True, 14)
    assert (terrorskull["item_level"], terrorskull["spec"], terrorskull["class"]) == (6, "Combat", "rogue")
    # No profile published yet: what the roster says, class and race from Battle.net's ids.
    brista = by_slug["brista-valorhart"]
    assert (brista["profile_found"], brista["class"], brista["item_level"]) == (False, "priest", None)


async def test_a_later_sync_reports_who_joined_and_who_left(
    characters_client: AsyncTestClient, battlenet: dict
) -> None:
    await characters_client.post(SYNC, headers=BOT)
    battlenet["roster"] = [member for member in battlenet["roster"] if member["character"]["slug"] != "legs-behindhead"]
    battlenet["roster"].append(roster_member("Newt", "Brightwater", rank=6, level=3))

    report = (await characters_client.post(SYNC, headers=BOT)).json()

    assert (report["joined"], report["left"]) == (["Newt Brightwater"], ["Legs Behindhead"])
    roster = {row["slug"] for row in (await characters_client.get("/api/characters/")).json()}
    assert "newt-brightwater" in roster
    assert "legs-behindhead" not in roster


async def test_the_sync_links_addon_characters_whose_name_only_one_roster_member_has(
    characters_client: AsyncTestClient, battlenet: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    battlenet["roster"].append(roster_member("Nox", "Otherkin", rank=6))
    async with db_sessionmaker() as session:
        session.add_all(
            [
                WowCharacter(name="Brista", realm="Whitemane", key="brista-whitemane"),
                WowCharacter(name="Nox", realm="Whitemane", key="nox-whitemane"),
            ]
        )
        await session.commit()

    report = (await characters_client.post(SYNC, headers=BOT)).json()

    assert report["characters_linked"] == 1
    async with db_sessionmaker() as session:
        rows = {row.name: row for row in (await session.execute(select(WowCharacter))).scalars()}
    assert (rows["Brista"].slug, rows["Brista"].surname, rows["Brista"].key) == (
        "brista-valorhart",
        "Valorhart",
        "brista-whitemane",
    )
    assert rows["Nox"].slug is None


async def test_only_the_bot_syncs_and_only_for_the_site_guild(characters_client: AsyncTestClient) -> None:
    assert (await characters_client.post(SYNC)).status_code == 401
    assert (await characters_client.post("/api/guilds/1/characters/sync", headers=BOT)).status_code == 404


async def test_a_character_page_is_fetched_once_then_served_from_the_database(
    characters_client: AsyncTestClient, battlenet: dict
) -> None:
    first = await characters_client.get("/api/characters/Terrorskull-Gloomstep")
    asked = _profile_requests(battlenet)
    second = await characters_client.get("/api/characters/terrorskull-gloomstep")

    assert first.status_code == 200
    assert _profile_requests(battlenet) == asked
    assert first.json() == second.json()
    assert "max-age=600" in first.headers["cloudflare-cdn-cache-control"]
    page = first.json()
    assert (page["slug"], page["name"], page["surname"], page["in_roster"]) == (
        TERRORSKULL,
        "Terrorskull",
        "Gloomstep",
        False,
    )
    sheet = page["sheet"]
    assert len(sheet["gear"]) == 11
    assert {"slot", "item_id", "name", "quality", "item_level", "enchantments"} <= set(sheet["gear"][0])
    assert sheet["talents"] == [{"name": "Combat", "points": 4}]
    assert [line["label"] for line in sheet["stats"]][:2] == ["Health", "Energy"]
    assert {skill["name"] for skill in sheet["professions"]} >= {"Leatherworking", "Skinning"}
    assert (sheet["mounts"], sheet["toys"]) == (2, 2)


async def test_a_character_battlenet_has_not_published_is_404_and_not_asked_for_again_soon(
    characters_client: AsyncTestClient, battlenet: dict
) -> None:
    first = await characters_client.get("/api/characters/nobody-here")
    asked = len(battlenet["requests"])
    second = await characters_client.get("/api/characters/nobody-here")

    assert (first.status_code, second.status_code) == (404, 404)
    assert "logs out" in first.json()["detail"]
    assert len(battlenet["requests"]) == asked
    assert (await characters_client.get("/api/characters/nohyphen")).status_code == 400


async def test_a_stale_character_is_fetched_again_and_served_as_stored_while_battlenet_is_down(
    characters_client: AsyncTestClient, battlenet: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await characters_client.get(f"/api/characters/{TERRORSKULL}")
    async with db_sessionmaker() as session:
        week_ago = datetime.now(UTC) - timedelta(days=7)
        await session.execute(update(BattlenetCharacter).values(fetched_at=week_ago, level=13))
        await session.commit()

    battlenet["down"] = True
    stale = await characters_client.get(f"/api/characters/{TERRORSKULL}")
    battlenet["down"] = False
    battlenet["failing"] = {"/equipment"}  # the summary answers, one part of the sheet doesn't
    part_down = await characters_client.get(f"/api/characters/{TERRORSKULL}")
    battlenet["failing"] = set()
    fresh = await characters_client.get(f"/api/characters/{TERRORSKULL}")

    assert (stale.status_code, stale.json()["level"]) == (200, 13)
    assert (part_down.status_code, part_down.json()["level"]) == (200, 13)
    assert (fresh.status_code, fresh.json()["level"]) == (200, 14)


async def test_search_finds_stored_characters_by_name_or_surname(characters_client: AsyncTestClient) -> None:
    await characters_client.post(SYNC, headers=BOT)

    by_surname = await characters_client.get("/api/characters/", params={"q": "gloom"})
    by_both = await characters_client.get("/api/characters/", params={"q": "nox zul"})

    assert [row["slug"] for row in by_surname.json()] == [TERRORSKULL]
    assert [row["slug"] for row in by_both.json()] == ["nox-zul"]
    assert (await characters_client.get("/api/characters/", params={"q": "z"})).status_code == 400


async def test_the_hero_boards_rank_roster_characters_with_a_profile(
    characters_client: AsyncTestClient, battlenet: dict
) -> None:
    battlenet["profiles"].add("psyence-spiritbound")
    await characters_client.get("/api/characters/psyence-spiritbound")  # looked up, but not in the guild
    await characters_client.post(SYNC, headers=BOT)

    boards = (await characters_client.get("/api/characters/boards")).json()

    assert [(entry["slug"], entry["value"]) for entry in boards["item_level"]] == [(TERRORSKULL, 6)]
    # Terrorskull has no honorable kills or achievement points yet; zeros don't make a board.
    assert boards["honorable_kills"] == boards["achievement_points"] == []


async def test_raid_signups_show_readiness_against_the_officers_minimum_item_level(
    characters_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await characters_client.post(SYNC, headers=BOT)
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind="raid",
            title="Molten Core",
            location="Molten Core",
            starts_at=datetime.now(UTC) + timedelta(days=1),
            size=40,
            status="scheduled",
            notes=None,
        )
        session.add(event)
        await session.commit()
        event_id = event.id
    signup = {"class": "rogue", "role": "dps", "status": "signed", "comment": None}

    await login_as(characters_client, discord_state, discord_id=8001, username="rogue")
    await characters_client.put(f"/api/events/{event_id}/signup", json={**signup, "character": "Terrorskull"})
    assert (await characters_client.put("/api/raid-readiness", json={"min_item_level": 10})).status_code == 403
    await login_as(characters_client, discord_state, discord_id=8002, username="officer", roles=[OFFICER_ROLE_ID])
    await characters_client.put(f"/api/events/{event_id}/signup", json={**signup, "character": "Thrall"})
    saved = await characters_client.put("/api/raid-readiness", json={"min_item_level": 10})

    detail = (await characters_client.get(f"/api/events/{event_id}")).json()

    assert saved.json() == {"min_item_level": 10}
    assert detail["min_item_level"] == 10
    readiness = {row["character"]: row["readiness"] for row in detail["signups"]}
    assert readiness["Terrorskull"] == {
        "slug": TERRORSKULL,
        "level": 14,
        "item_level": 6,
        "spec": "Combat",
        "below_minimum": True,
    }
    assert readiness["Thrall"] is None


def _level(battlenet: dict, slug: str, level: int) -> None:
    next(member for member in battlenet["roster"] if member["character"]["slug"] == slug)["character"]["level"] = level


async def test_reaching_level_40_or_60_queues_one_milestone_for_the_bot(
    characters_client: AsyncTestClient, battlenet: dict
) -> None:
    pending_url = f"/api/guilds/{GUILD_ID}/characters/milestones/pending"
    battlenet["roster"] += [
        roster_member("Climber", "Up", rank=6, level=39),
        roster_member("Rocket", "Fast", rank=6, level=38),
    ]
    await characters_client.post(SYNC, headers=BOT)
    assert (await characters_client.get(pending_url, headers=BOT)).json() == []

    _level(battlenet, "climber-up", 41)
    _level(battlenet, "rocket-fast", 60)
    battlenet["roster"].append(roster_member("Late", "Joiner", rank=6, level=60))
    await characters_client.post(SYNC, headers=BOT)
    await characters_client.post(SYNC, headers=BOT)  # nothing new: no second milestone

    pending = (await characters_client.get(pending_url, headers=BOT)).json()
    # Passing 40 and 60 at once announces 60 only; joining the guild already at 60 announces nothing.
    assert sorted((row["slug"], row["level"]) for row in pending) == [("climber-up", 40), ("rocket-fast", 60)]
    posted = await characters_client.post(
        f"/api/guilds/{GUILD_ID}/characters/milestones/{pending[0]['id']}/posted",
        headers=BOT,
        json={"discord_message_id": 123},
    )
    assert posted.status_code == 204
    remaining = (await characters_client.get(pending_url, headers=BOT)).json()
    assert [row["id"] for row in remaining] == [pending[1]["id"]]
    public = (await characters_client.get("/api/characters/milestones")).json()
    assert {row["slug"] for row in public} == {"climber-up", "rocket-fast"}
    wrong_guild = "/api/guilds/1/characters/milestones/pending"
    assert (await characters_client.get(wrong_guild, headers=BOT)).status_code == 404


async def test_officers_vet_a_recruit_by_setting_their_battlenet_character(
    characters_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        recruit = GuildRecruit(character="Terrorskull", at=datetime.now(UTC))
        session.add(recruit)
        await session.commit()
        url = f"/api/epgp/recruits/{recruit.id}"
    await login_as(characters_client, discord_state, discord_id=8101, username="member")
    assert (await characters_client.put(url, json={"slug": TERRORSKULL})).status_code == 403
    await login_as(characters_client, discord_state, discord_id=8102, username="officer", roles=[OFFICER_ROLE_ID])

    set_slug = await characters_client.put(url, json={"slug": "Terrorskull-Gloomstep"})
    unknown = await characters_client.put(url, json={"slug": "nobody-here"})
    status_only = await characters_client.put(url, json={"status": "trial"})
    listed = (await characters_client.get("/api/epgp/recruits/")).json()["recruits"]

    assert set_slug.status_code == 200
    vetting = set_slug.json()["battlenet"]
    assert (vetting["slug"], vetting["guild_name"], vetting["level"], vetting["item_level"]) == (
        TERRORSKULL,
        "Fuzion",
        14,
        6,
    )
    assert unknown.status_code == 404
    assert (status_only.json()["status"], status_only.json()["slug"]) == ("trial", TERRORSKULL)
    assert listed[0]["battlenet"]["guild_name"] == "Fuzion"
