"""The guild directory: ``SQX1:`` ``directory``/``item_names``/``recipe_names`` sections (``addon/docs/
directory.md`` in the addon repo is the contract), import upsert/newest-``at``-wins/tombstone/replace semantics,
and the ``GET /api/guild/directory``, ``/market``, ``/stock`` HTTP endpoints."""

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from sidequest_common.models import CharacterProfession, ProfessionRecipe
from sidequest_common.schemas import (
    MARKET_REQUEST_NOTE_MAX,
    MAX_DIRECTORY_RECIPES_PER_PROFESSION,
    MAX_MARKET_SELL,
    MAX_PROFESSION_PAIRS,
    MAX_STOCK_ENTRIES,
    DirMarketData,
    DirMarketRequest,
    DirProfession,
    DirStockData,
    ExportDirectorySections,
    ExportPayload,
)
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

RECORDER = "Officername-Whitemane"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXPORTED_AT = 1793500000


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
        "directory": [],
        "item_names": {},
        "recipe_names": {},
    }
    payload.update(overrides)
    return payload


def _directory_entry(character: str, **sections: dict) -> dict:
    return {"character": character, "sections": sections}


async def _login_officer(client: AsyncTestClient, discord_state: dict, *, discord_id: int = 100) -> None:
    response = await login_as(client, discord_state, discord_id=discord_id, roles=[OFFICER_ROLE_ID])
    assert response.status_code == 302, response.text


# --- Schema validation / limits -----------------------------------------------------------------------------


def test_export_payload_accepts_a_directory_entry() -> None:
    payload = _base_payload(
        directory=[
            _directory_entry(
                "Crafty-Whitemane",
                prof={
                    "v": "aaaaaaaa",
                    "at": EXPORTED_AT,
                    "d": {"professions": [{"name": "Tailoring", "skill_line": 197, "skill": 285, "max_skill": 300}]},
                },
            )
        ]
    )
    parsed = ExportPayload.model_validate(payload)
    assert parsed.directory[0].character == "Crafty-Whitemane"
    prof = parsed.directory[0].sections.prof
    assert prof is not None
    assert prof.d is not None
    assert prof.d.professions[0].name == "Tailoring"


def test_directory_section_missing_d_key_is_a_tombstone() -> None:
    """The addon's JSON codec omits a nil ``d`` entirely rather than sending ``null``; both parse the same."""
    sections = ExportDirectorySections.model_validate({"market": {"v": "aaaaaaaa", "at": EXPORTED_AT}})
    assert sections.market is not None
    assert sections.market.d is None


def test_directory_section_explicit_null_d_is_also_a_tombstone() -> None:
    sections = ExportDirectorySections.model_validate({"market": {"v": "aaaaaaaa", "at": EXPORTED_AT, "d": None}})
    assert sections.market is not None
    assert sections.market.d is None


def test_directory_unknown_section_key_is_ignored() -> None:
    sections = ExportDirectorySections.model_validate({"future_section": {"anything": True}})
    assert sections.prof is None
    assert sections.char is None
    assert sections.stock is None


def test_directory_profession_recipes_over_the_limit_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DirProfession(
            name="Tailoring",
            skill_line=197,
            skill=300,
            max_skill=300,
            recipes=list(range(MAX_DIRECTORY_RECIPES_PER_PROFESSION + 1)),
        )


def test_market_request_note_over_80_chars_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DirMarketRequest(id="x", item_id=1, qty=1, note="x" * (MARKET_REQUEST_NOTE_MAX + 1), at=EXPORTED_AT)


def test_market_sell_over_the_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DirMarketData(sell=[{"item_id": i, "qty": 1} for i in range(MAX_MARKET_SELL + 1)])


def test_stock_entries_over_the_limit_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DirStockData(bags=[(i, 1) for i in range(MAX_STOCK_ENTRIES + 1)])


def test_profession_pairs_limit_covers_a_150_member_guild() -> None:
    """2 primaries + 3 fixed secondaries (Cooking/Fishing/First Aid) each, across 150 members."""
    assert MAX_PROFESSION_PAIRS >= 150 * 5


# --- Import: prof (shared CharacterProfession/ProfessionRecipe tables) -----------------------------------------


async def test_directory_prof_replaces_professions_wholesale_and_feeds_crafters(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8001)
    payload = _base_payload(
        directory=[
            _directory_entry(
                "Crafty-Whitemane",
                prof={
                    "v": "aaaaaaaa",
                    "at": EXPORTED_AT,
                    "d": {
                        "professions": [
                            {
                                "name": "Tailoring",
                                "skill_line": 197,
                                "skill": 285,
                                "max_skill": 300,
                                "recipes": [18560],
                                "recipes_at": EXPORTED_AT,
                            },
                            {"name": "Cooking", "skill_line": 185, "skill": 150, "max_skill": 300},
                        ]
                    },
                },
            )
        ],
        recipe_names={"18560": "Mooncloth"},
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    assert response.json()["directory"]["prof"] == {"updated": 1, "skipped": 0}

    async with db_sessionmaker() as session:
        rows = (await session.execute(select(CharacterProfession))).scalars().all()
        assert {row.profession for row in rows} == {"Tailoring", "Cooking"}

    crafters = await member_client.get("/api/guild/crafters", params={"q": "Mooncloth"})
    assert crafters.status_code == 200, crafters.text
    assert crafters.json()["results"][0]["crafters"][0]["character"] == "crafty-whitemane"

    # A second, newer `prof` section replaces the set wholesale: Cooking drops, Tailoring's skill updates.
    payload2 = _base_payload(
        directory=[
            _directory_entry(
                "Crafty-Whitemane",
                prof={
                    "v": "bbbbbbbb",
                    "at": EXPORTED_AT + 100,
                    "d": {"professions": [{"name": "Tailoring", "skill_line": 197, "skill": 300, "max_skill": 300}]},
                },
            )
        ],
    )
    response2 = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload2)})
    assert response2.status_code == 200, response2.text
    async with db_sessionmaker() as session:
        rows = (await session.execute(select(CharacterProfession))).scalars().all()
        assert {row.profession for row in rows} == {"Tailoring"}
        assert rows[0].skill == 300


async def test_directory_prof_recipe_names_kept_when_missing_next_time(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8002)
    first = _base_payload(
        directory=[
            _directory_entry(
                "Namer-Whitemane",
                prof={
                    "v": "aaaaaaaa",
                    "at": EXPORTED_AT,
                    "d": {
                        "professions": [
                            {"name": "Tailoring", "skill_line": 197, "skill": 300, "max_skill": 300, "recipes": [18560]}
                        ]
                    },
                },
            )
        ],
        recipe_names={"18560": "Mooncloth"},
    )
    await member_client.post("/api/epgp/imports", json={"payload": _export_string(first)})

    second = _base_payload(
        directory=[
            _directory_entry(
                "Namer-Whitemane",
                prof={
                    "v": "bbbbbbbb",
                    "at": EXPORTED_AT + 10,
                    "d": {
                        "professions": [
                            {"name": "Tailoring", "skill_line": 197, "skill": 300, "max_skill": 300, "recipes": [18560]}
                        ]
                    },
                },
            )
        ],
    )  # no recipe_names this time
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(second)})
    assert response.status_code == 200, response.text

    async with db_sessionmaker() as session:
        row = (await session.execute(select(ProfessionRecipe).where(ProfessionRecipe.recipe_id == 18560))).scalar_one()
        assert row.name == "Mooncloth"


async def test_directory_prof_tombstone_removes_professions(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8003)
    payload = _base_payload(
        directory=[
            _directory_entry(
                "Ghosty-Whitemane",
                prof={
                    "v": "aaaaaaaa",
                    "at": EXPORTED_AT,
                    "d": {"professions": [{"name": "Mining", "skill_line": 186, "skill": 60, "max_skill": 300}]},
                },
            )
        ],
    )
    await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})

    tombstone = _base_payload(
        directory=[_directory_entry("Ghosty-Whitemane", prof={"v": "bbbbbbbb", "at": EXPORTED_AT + 10})]
    )  # `d` omitted entirely, like the addon's codec
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(tombstone)})
    assert response.status_code == 200, response.text
    assert response.json()["directory"]["prof"] == {"updated": 1, "skipped": 0}

    async with db_sessionmaker() as session:
        rows = (await session.execute(select(CharacterProfession))).scalars().all()
        assert rows == []


# --- Import: newest `at` wins ------------------------------------------------------------------------------


async def test_directory_section_skips_an_older_at(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=8004)
    newer = _base_payload(
        directory=[
            _directory_entry(
                "Timey-Whitemane",
                char={"v": "aaaaaaaa", "at": EXPORTED_AT + 1000, "d": {"level": 60, "class": "MAGE", "race": "Human"}},
            )
        ]
    )
    first = await member_client.post("/api/epgp/imports", json={"payload": _export_string(newer)})
    assert first.status_code == 200, first.text
    assert first.json()["directory"]["char"] == {"updated": 1, "skipped": 0}

    older = _base_payload(
        directory=[
            _directory_entry(
                "Timey-Whitemane",
                char={"v": "bbbbbbbb", "at": EXPORTED_AT, "d": {"level": 1, "class": "WARRIOR", "race": "Orc"}},
            )
        ]
    )
    second = await member_client.post("/api/epgp/imports", json={"payload": _export_string(older)})
    assert second.status_code == 200, second.text
    assert second.json()["directory"]["char"] == {"updated": 0, "skipped": 1}

    directory = await member_client.get("/api/guild/directory")
    row = next(c for c in directory.json()["characters"] if c["character"] == "timey-whitemane")
    assert row["level"] == 60  # unchanged by the stale update


async def test_directory_char_tombstone_deletes_the_row(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=8005)
    payload = _base_payload(
        directory=[
            _directory_entry(
                "Vanisher-Whitemane",
                char={"v": "aaaaaaaa", "at": EXPORTED_AT, "d": {"level": 60, "class": "MAGE", "race": "Human"}},
            )
        ]
    )
    await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})

    tombstone = _base_payload(
        directory=[_directory_entry("Vanisher-Whitemane", char={"v": "bbbbbbbb", "at": EXPORTED_AT + 10})]
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(tombstone)})
    assert response.status_code == 200, response.text
    assert response.json()["directory"]["char"] == {"updated": 1, "skipped": 0}

    directory = await member_client.get("/api/guild/directory")
    assert not any(c["character"] == "vanisher-whitemane" for c in directory.json()["characters"])


# --- Import: cd, market, stock --------------------------------------------------------------------------------


async def test_directory_cooldowns_import_and_api_shape(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=8006)
    payload = _base_payload(
        directory=[
            _directory_entry(
                "Cooler-Whitemane",
                cd={
                    "v": "aaaaaaaa",
                    "at": EXPORTED_AT,
                    "d": {"cooldowns": [{"key": "transmute", "ready_at": 1793460000}]},
                },
            )
        ]
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    assert response.json()["directory"]["cd"] == {"updated": 1, "skipped": 0}

    directory = await member_client.get("/api/guild/directory")
    row = next(c for c in directory.json()["characters"] if c["character"] == "cooler-whitemane")
    assert row["cooldowns"][0]["key"] == "transmute"
    assert row["freshness"]["cd"] is not None
    assert row["freshness"]["prof"] is None


async def test_directory_market_import_and_api_shape(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=8007)
    payload = _base_payload(
        directory=[
            _directory_entry(
                "Trader-Whitemane",
                market={
                    "v": "aaaaaaaa",
                    "at": EXPORTED_AT,
                    "d": {
                        "sell": [{"item_id": 14048, "price": 12000, "qty": 20, "crafted": False}],
                        "buy": [{"item_id": 12360, "price": 35000}],
                        "requests": [
                            {
                                "id": "Trader-Whitemane-1",
                                "item_id": 12360,
                                "qty": 4,
                                "price": 35000,
                                "note": "for Arcanite Reaper",
                                "at": EXPORTED_AT,
                            }
                        ],
                    },
                },
            )
        ],
        item_names={"14048": "Runecloth", "12360": "Arcanite Bar"},
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    assert response.json()["directory"]["market"] == {"updated": 1, "skipped": 0}

    market = await member_client.get("/api/guild/market")
    assert market.status_code == 200, market.text
    body = market.json()
    assert body["sell"][0]["item_name"] == "Runecloth"
    assert body["sell"][0]["price"] == 12000
    assert body["buy"][0]["item_name"] == "Arcanite Bar"
    assert body["requests"][0]["note"] == "for Arcanite Reaper"

    # Lists replace wholesale: a second, newer import with empty lists drops everything.
    second = _base_payload(
        directory=[
            _directory_entry(
                "Trader-Whitemane",
                market={"v": "bbbbbbbb", "at": EXPORTED_AT + 10, "d": {"sell": [], "buy": [], "requests": []}},
            )
        ]
    )
    await member_client.post("/api/epgp/imports", json={"payload": _export_string(second)})
    market2 = await member_client.get("/api/guild/market")
    assert market2.json() == {"sell": [], "buy": [], "requests": []}


async def test_directory_stock_who_has_it(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=8008)
    payload = _base_payload(
        directory=[
            _directory_entry(
                "Packrat-Whitemane",
                stock={
                    "v": "aaaaaaaa",
                    "at": EXPORTED_AT,
                    "d": {"bags": [[14048, 20], [12360, 3]], "bank": [[14256, 40]], "bank_at": EXPORTED_AT},
                },
            )
        ],
        item_names={"14048": "Runecloth"},
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    assert response.json()["directory"]["stock"] == {"updated": 1, "skipped": 0}

    stock = await member_client.get("/api/guild/stock", params={"item_id": 14048})
    assert stock.status_code == 200, stock.text
    body = stock.json()
    assert body["item_name"] == "Runecloth"
    assert body["rows"][0]["bags"] == 20
    assert body["rows"][0]["bank"] == 0

    none_found = await member_client.get("/api/guild/stock", params={"item_id": 99999})
    assert none_found.status_code == 200, none_found.text
    assert none_found.json()["rows"] == []


# --- Import result shape / auth ------------------------------------------------------------------------------


async def test_import_result_includes_directory_counts_even_when_empty(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await _login_officer(member_client, discord_state, discord_id=8009)
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(_base_payload())})
    assert response.status_code == 200, response.text
    directory_counts = response.json()["directory"]
    for section in ("prof", "char", "cd", "market", "stock"):
        assert directory_counts[section] == {"updated": 0, "skipped": 0}


async def test_directory_endpoints_require_a_member_session(member_client: AsyncTestClient) -> None:
    for path in ("/api/guild/directory", "/api/guild/market"):
        response = await member_client.get(path)
        assert response.status_code == 401, response.text
    response = await member_client.get("/api/guild/stock", params={"item_id": 1})
    assert response.status_code == 401, response.text


# --- Real addon fixture ---------------------------------------------------------------------------------------


async def test_real_addon_directory_fixture_imports_prof_stock_and_market_tombstone(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Generated by the addon's ``tests/test_directory.lua``: a ``prof`` scan with one recipe, a ``stock`` section
    with one bagged item, and a tombstoned ``market`` section (``d`` absent, matching the addon codec's nil
    handling) for a second character."""
    raw_text = (FIXTURES_DIR / "export_v2_directory.txt").read_text()
    await _login_officer(member_client, discord_state, discord_id=8010)

    response = await member_client.post("/api/epgp/imports", json={"payload": raw_text})
    assert response.status_code == 200, response.text
    counts = response.json()["directory"]
    assert counts["prof"] == {"updated": 1, "skipped": 0}
    assert counts["stock"] == {"updated": 1, "skipped": 0}
    assert counts["market"] == {"updated": 1, "skipped": 0}

    async with db_sessionmaker() as session:
        rows = (await session.execute(select(CharacterProfession))).scalars().all()
        assert len(rows) == 1
        assert rows[0].profession == "Tailoring"
        recipe = (
            await session.execute(select(ProfessionRecipe).where(ProfessionRecipe.recipe_id == 18560))
        ).scalar_one()
        assert recipe.name == "Mooncloth"

    stock = await member_client.get("/api/guild/stock", params={"item_id": 14048})
    assert stock.status_code == 200, stock.text
    body = stock.json()
    assert body["item_name"] == "Runecloth"
    assert body["rows"][0]["character"] == "tailor-whitemane"
    assert body["rows"][0]["bags"] == 5

    # "Other-Whitemane"'s `market` section is a tombstone (d absent): no market data to show.
    market = await member_client.get("/api/guild/market")
    assert market.status_code == 200, market.text
    assert market.json() == {"sell": [], "buy": [], "requests": []}

    # Re-importing is idempotent: the same `at` is not newer, so sections are skipped the second time.
    second = await member_client.post("/api/epgp/imports", json={"payload": raw_text})
    assert second.status_code == 200, second.text
    second_counts = second.json()["directory"]
    assert second_counts["prof"] == {"updated": 0, "skipped": 1}
    assert second_counts["stock"] == {"updated": 0, "skipped": 1}
