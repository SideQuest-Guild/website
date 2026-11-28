"""Sims: request validation, item resolution, SIML generation, result parsing, the queue limit, and the runner."""

import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from litestar.testing import AsyncTestClient
from wow import AsyncClient

from sidequest_api.app import create_app
from sidequest_api.domain.characters.services import CharactersService
from sidequest_api.domain.sims import engine
from sidequest_api.domain.sims.runner import _claim_next, _run_one
from sidequest_api.domain.sims.services import SimsService, prepare_sim
from sidequest_common.models import BattlenetCharacter, SimJob
from sidequest_common.schemas import SimItem, SimRequest
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings, WowSimsSettings
from tests.conftest import GUILD_ID, TEST_API_KEY
from tests.unit.api.fake_battlenet import battlenet, forget_battlenet_state, transport

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sidequest_common.schemas import SimSlot

SIMS_PATH = f"/api/guilds/{GUILD_ID}/sims"


# ---------- a minimal fake wowsims checkout: names/db tables and one spec's SIML preset ----------


@pytest.fixture
def wowsims_dir(tmp_path: Path) -> Path:
    root = tmp_path / "wowsims"
    (root / "sim" / "siml").mkdir(parents=True)
    (root / "assets" / "database").mkdir(parents=True)
    spec_dir = root / "ui" / "specs" / "paladin" / "protection"
    (spec_dir / "apls").mkdir(parents=True)

    names = {
        "items": {
            "test_helm": 1001,
            "old_sword": 2001,
            "new_sword": 2002,
            "test_ring": 3001,
            "test_mace": 2003,
            "test_shield": 2004,
            "test_off_hand_dagger": 2005,
        },
        "suffixes": {"of_the_bear": "of_the_bear"},
        "enchants": {"minor_spell_power": "minor_spell_power"},
    }
    (root / "sim" / "siml" / "names.json").write_text(json.dumps(names))

    db = {
        "items": [
            {"id": 1001, "name": "Test Helm", "type": 1},
            {"id": 2001, "name": "Old Sword", "type": 13, "handType": 1},
            {"id": 2002, "name": "New Sword", "type": 13, "handType": 1},
            {"id": 3001, "name": "Test Ring", "type": 11},
            {"id": 2003, "name": "Test Mace", "type": 13, "handType": 2, "weaponType": 4},
            {"id": 2004, "name": "Test Shield", "type": 13, "handType": 3, "weaponType": 7},
            {"id": 2005, "name": "Test Off Hand Dagger", "type": 13, "handType": 3, "weaponType": 2},
        ]
    }
    (root / "assets" / "database" / "db.json").write_text(json.dumps(db))

    (spec_dir / "defaults.siml").write_text(
        'siml 1\nspec protection_paladin\ntalents "050050002-05302102213301531-502"\n'
        'use "apls/default.apl.siml"\n\nsettings:\n  race human\n'
    )
    (spec_dir / "apls" / "default.apl.siml").write_text(
        "siml 1\nspec protection_paladin\n\npriority:\n  cast judgement\n"
    )
    return root


@pytest.fixture
def sim_app(database_url: str, wowsims_dir: Path, battlenet: dict) -> Litestar:
    return create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        WebSettings(_env_file=None, BATTLENET_CLIENT_ID="bnet-client-id", BATTLENET_CLIENT_SECRET="bnet-client-secret"),
        WowSimsSettings(DIR=str(wowsims_dir), RUNNER=False),
        game_data_transport=transport(battlenet),
    )


@pytest.fixture
async def sim_client(sim_app: Litestar) -> AsyncIterator[AsyncTestClient[Litestar]]:
    async with AsyncTestClient(app=sim_app) as test_client:
        test_client.headers["X-API-Key"] = TEST_API_KEY
        yield test_client


async def _store_character(
    session: AsyncSession, *, slug: str = "legs-behindhead", name: str = "Legs", surname: str = "Behindhead"
) -> BattlenetCharacter:
    sheet = {
        "gear": [
            {
                "slot": "HEAD",
                "slot_name": "Head",
                "item_id": 1001,
                "name": "Test Helm",
                "quality": "RARE",
                "item_level": 50,
                "enchantments": ["Enchanted: Mystery Glow"],
            },
            {
                "slot": "MAIN_HAND",
                "slot_name": "Main Hand",
                "item_id": 2001,
                "name": "Old Sword",
                "quality": "RARE",
                "item_level": 50,
                "enchantments": [],
            },
        ],
        "stats": [],
        "talents": [],
        "professions": [],
        "reputations": [],
        "recent_achievements": [],
        "hunter_pets": [],
        "mounts": 0,
        "pets": 0,
        "toys": 0,
        "quests_completed": None,
    }
    character = BattlenetCharacter(
        slug=slug,
        blizzard_id=1,
        name=name,
        surname=surname,
        level=60,
        wow_class="paladin",
        race="Human",
        faction="Alliance",
        in_roster=True,
        profile_found=True,
        spec="Protection",
        sheet=sheet,
        fetched_at=datetime.now(UTC),
    )
    session.add(character)
    await session.flush()
    await session.commit()
    return character


# ---------- item resolution ----------


def test_resolves_item_by_numeric_id(wowsims_dir: Path) -> None:
    item_id, name = engine.ItemDB(wowsims_dir).resolve_item("2002")
    assert (item_id, name) == (2002, "new_sword")


def test_resolves_item_by_wowhead_url(wowsims_dir: Path) -> None:
    item_id, name = engine.ItemDB(wowsims_dir).resolve_item("https://wow-forever.gg/item=2002/new-sword")
    assert (item_id, name) == (2002, "new_sword")


def test_resolves_item_by_case_insensitive_name(wowsims_dir: Path) -> None:
    item_id, name = engine.ItemDB(wowsims_dir).resolve_item("NEW sword")
    assert (item_id, name) == (2002, "new_sword")


def test_unknown_item_raises_with_suggestions(wowsims_dir: Path) -> None:
    with pytest.raises(engine.SimEngineError, match="unknown item"):
        engine.ItemDB(wowsims_dir).resolve_item("nonexistent gizmo")


def test_ambiguous_slot_item_needs_a_slot_unless_single_slot(wowsims_dir: Path) -> None:
    db = engine.ItemDB(wowsims_dir)
    resolved = engine.resolve_sim_item(SimItem(item="test_ring"), db, dual_wield=False)
    assert resolved.candidate_slots == ("finger1", "finger2")
    # A weapon with one candidate slot resolves without needing one.
    resolved = engine.resolve_sim_item(SimItem(item="new_sword"), db, dual_wield=False)
    assert resolved.candidate_slots == ("main_hand",)


def test_item_that_does_not_fit_requested_slot_errors(wowsims_dir: Path) -> None:
    db = engine.ItemDB(wowsims_dir)
    with pytest.raises(engine.SimEngineError, match="doesn't fit"):
        engine.resolve_sim_item(SimItem(item="new_sword", slot="head"), db, dual_wield=False)


def test_one_hand_weapon_goes_in_the_off_hand_only_for_dual_wielders(wowsims_dir: Path) -> None:
    db = engine.ItemDB(wowsims_dir)
    assert engine.resolve_sim_item(SimItem(item="test_mace"), db, dual_wield=False).candidate_slots == ("main_hand",)
    assert engine.resolve_sim_item(SimItem(item="test_mace"), db, dual_wield=True).candidate_slots == (
        "main_hand",
        "off_hand",
    )
    with pytest.raises(engine.SimEngineError, match="can dual-wield"):
        engine.resolve_sim_item(SimItem(item="test_mace", slot="off_hand"), db, dual_wield=False)
    with pytest.raises(engine.SimEngineError, match="can dual-wield"):
        engine.resolve_sim_item(SimItem(item="test_off_hand_dagger"), db, dual_wield=False)
    # Shields go in the off hand for everyone.
    assert engine.resolve_sim_item(SimItem(item="test_shield"), db, dual_wield=False).candidate_slots == ("off_hand",)


# ---------- SIML generation ----------


def test_build_siml_includes_the_swapped_item() -> None:
    gear: dict[SimSlot, engine.GearEntry] = {"main_hand": engine.GearEntry(name="new_sword", item_id=2002)}
    siml_text = engine.build_siml(
        class_name="paladin",
        spec="protection",
        race="Dwarf",
        talents="050050002-05302102213301531-502",
        rotation=Path("/sims/rotation.apl.siml"),
        gear=gear,
        targets=1,
        mob="humanoid",
        duration=90,
        role="tank",
    )
    assert "spec protection_paladin" in siml_text
    assert "main_hand new_sword" in siml_text
    assert "mob_type=humanoid" in siml_text
    assert "tanks player1" in siml_text  # tank-only setting
    assert 'use "/sims/rotation.apl.siml"' in siml_text


def test_build_siml_omits_tank_settings_for_dps_role() -> None:
    siml_text = engine.build_siml(
        class_name="hunter",
        spec="dps",
        race="Orc",
        talents="",
        rotation=Path("/sims/rotation.apl.siml"),
        gear={},
        targets=1,
        mob="humanoid",
        duration=90,
        role="dps",
    )
    assert "tanks player1" not in siml_text
    assert "in_front_of_target" not in siml_text


def test_inline_rotation_keeps_only_the_rotation_of_a_defaults_file() -> None:
    defaults = (
        'siml 1\nspec balance_druid\ntalents "1-2-3"\n\nsettings:\n  race tauren\n\ngear:\n  head some_cap\n\n'
        "var ${Use Hurricane} = true\n\nbuffs:\n  arcane_brilliance\n\napl:\n  x 1\n\nprepull:\n  -1s cast wrath\n\n"
        'priority:\n  cast moonfire\n  group "Filler"\n\ngroup "Filler":\n  cast wrath\n\nencounter:\n  duration 90\n'
    )
    rotation = engine._inline_rotation(defaults)
    assert rotation is not None
    for kept in ("var ${Use Hurricane}", "apl:", "prepull:", "priority:", "  cast moonfire", 'group "Filler":'):
        assert kept in rotation
    for dropped in ("settings:", "race tauren", "gear:", "some_cap", "buffs:", "encounter:", "talents"):
        assert dropped not in rotation


def test_inline_rotation_is_none_without_a_priority_list() -> None:
    assert engine._inline_rotation("siml 1\nspec rogue\n\nsettings:\n  race human\n") is None


@pytest.mark.parametrize(
    ("class_name", "spec", "level", "match"),
    [
        ("priest", "healer", 60, "no healing rotation"),
        ("warlock", "dps", 60, "wowsims website"),
        ("paladin", "protection", 54, "only models level 60"),
    ],
)
def test_check_simmable_refuses_unsupported_specs_and_low_levels(
    class_name: str, spec: str, level: int, match: str
) -> None:
    with pytest.raises(engine.SimEngineError, match=match):
        engine.check_simmable(class_name, spec, level)


def test_check_simmable_accepts_a_level_55_tank() -> None:
    engine.check_simmable("paladin", "protection", 55)


# ---------- result parsing from a canned wowsimcli JSON output ----------


def test_metrics_from_player_parses_a_canned_result() -> None:
    player = {
        "dps": {"avg": 219.5, "stdev": 19.4},
        "threat": {"avg": 538.9, "stdev": 53.2},
        "dtps": {"avg": 134.2, "stdev": 15.0},
        "hps": {"avg": 0, "stdev": 0},
    }
    metrics = engine.metrics_from_player(player, "tank")
    assert metrics["dps"] == pytest.approx(219.5)
    assert metrics["tps"] == pytest.approx(538.9)
    assert metrics["dtps"] == pytest.approx(134.2)
    assert metrics["hps"] is None  # a tank's hps is never reported, even if the CLI happens to emit one


def test_delta_pct_and_noise() -> None:
    assert engine.delta_pct(100.0, 108.5) == pytest.approx(8.5)
    assert engine.delta_pct(None, 108.5) is None
    assert engine.is_noise(100.0, 100.5, base_sd=50.0, swapped_sd=50.0, iterations=100) is True
    assert engine.is_noise(100.0, 150.0, base_sd=1.0, swapped_sd=1.0, iterations=1000) is False


# ---------- request validation (400s) ----------


async def test_queue_sim_rejects_unknown_character(sim_client: AsyncTestClient) -> None:
    response = await sim_client.post(
        SIMS_PATH, json={"character": "Nobody Atall", "swaps": [{"item": "new_sword", "slot": "main_hand"}]}
    )
    assert response.status_code == 400
    assert "unknown character" in response.json()["detail"]


async def test_queue_sim_rejects_unknown_item(
    sim_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        await _store_character(session)
    response = await sim_client.post(
        SIMS_PATH,
        json={"character": "Legs Behindhead", "swaps": [{"item": "not a real item", "slot": "main_hand"}]},
    )
    assert response.status_code == 400
    assert "unknown item" in response.json()["detail"]


async def test_queue_sim_accepts_a_valid_swap(
    sim_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        await _store_character(session)
    response = await sim_client.post(
        SIMS_PATH,
        json={"character": "Legs Behindhead", "swaps": [{"item": "new_sword", "slot": "main_hand"}]},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["position"] == 0


async def test_get_unknown_sim_job_404s(sim_client: AsyncTestClient) -> None:
    response = await sim_client.get(f"{SIMS_PATH}/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# ---------- the 429 limit ----------


async def test_queue_limit_429s_a_fourth_pending_job(
    sim_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        await _store_character(session)
    body = {"character": "Legs Behindhead", "swaps": [{"item": "new_sword", "slot": "main_hand"}], "requested_by": "42"}
    for _ in range(3):
        response = await sim_client.post(SIMS_PATH, json=body)
        assert response.status_code == 202
    fourth = await sim_client.post(SIMS_PATH, json=body)
    assert fourth.status_code == 429
    assert "already have" in fourth.json()["detail"]


# ---------- the runner, with a fake CLI script ----------


@pytest.fixture
def fake_wowsimcli(wowsims_dir: Path) -> Path:
    """A fake ``wowsimcli`` that ignores its input and prints a canned ``sim`` result."""
    script = wowsims_dir / "bin" / "wowsimcli"
    script.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "raidMetrics": {
            "parties": [
                {
                    "players": [
                        {
                            "dps": {"avg": 220.0, "stdev": 20.0},
                            "threat": {"avg": 540.0, "stdev": 50.0},
                            "dtps": {"avg": 130.0, "stdev": 10.0},
                            "hps": {"avg": 0, "stdev": 0},
                        }
                    ]
                }
            ]
        }
    }
    script.write_text(f"#!/usr/bin/env python3\nimport sys\nprint('''{json.dumps(payload)}''')\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _fake_game_data(battlenet: dict) -> AsyncClient:
    """A real ``AsyncClient``, answered by the fake Battle.net transport, for tests that need the type but not a
    network call (the character is already stored fresh, so the runner never dials out)."""
    return AsyncClient(
        "bnet-client-id", "bnet-client-secret", http_client=httpx.AsyncClient(transport=transport(battlenet))
    )


async def test_prepare_sim_builds_one_comparison_for_a_single_slot_swap(
    wowsims_dir: Path, battlenet: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        await _store_character(session)
        request = SimRequest(character="Legs Behindhead", swaps=[SimItem(item="new_sword", slot="main_hand")])
        prepared = await prepare_sim(
            request,
            characters_service=CharactersService(session=session),
            game_data=_fake_game_data(battlenet),
            wowsims_dir=wowsims_dir,
        )
        assert len(prepared.comparisons) == 1
        assert prepared.role == "tank"
        assert prepared.comparisons[0].gear["main_hand"].name == "new_sword"
        assert prepared.baseline["main_hand"].name == "old_sword"


async def test_wearing_drops_notes_about_the_sheet_piece_it_replaces(
    wowsims_dir: Path, battlenet: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        await _store_character(session)
        swap = SimItem(item="new_sword", slot="main_hand")

        async def notes(*wearing: SimItem) -> list[str]:
            prepared = await prepare_sim(
                SimRequest(character="Legs Behindhead", swaps=[swap], wearing=list(wearing)),
                characters_service=CharactersService(session=session),
                game_data=_fake_game_data(battlenet),
                wowsims_dir=wowsims_dir,
            )
            return prepared.notes

        assert any("Mystery Glow" in note for note in await notes())
        assert not any("Mystery Glow" in note for note in await notes(SimItem(item="test_helm", slot="head")))


async def test_runner_runs_a_queued_job_end_to_end(
    wowsims_dir: Path, battlenet: dict, fake_wowsimcli: Path, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        await _store_character(session)
        request = SimRequest(character="Legs Behindhead", swaps=[SimItem(item="new_sword", slot="main_hand")])
        service = SimsService(session)

        job_schema = await service.queue(
            request,
            characters_service=CharactersService(session=session),
            game_data=_fake_game_data(battlenet),
            wowsims_dir=wowsims_dir,
        )

    async with db_sessionmaker() as session:
        job = await _claim_next(session, dialect="sqlite")
        assert job is not None
        assert job.id == job_schema.id
        await _run_one(
            job, session, wowsims_dir=wowsims_dir, wowsimcli=fake_wowsimcli, game_data=_fake_game_data(battlenet)
        )

    async with db_sessionmaker() as session:
        finished = await session.get(SimJob, job_schema.id)
        assert finished is not None
        assert finished.status == "done", finished.error
        assert finished.result is not None
        assert finished.result["comparisons"][0]["rows"][0]["swapped"]["tps"] == pytest.approx(540.0)
        assert finished.result["comparisons"][0]["rows"][0]["delta_pct"]["tps"] is not None
