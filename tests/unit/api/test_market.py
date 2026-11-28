"""The guild market report: the feed's key and storage, the report's access rules, and the report's math."""

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
from litestar.testing import AsyncTestClient
from pydantic import SecretStr

from sidequest_api.app import create_app
from sidequest_api.domain.market.report import (
    ItemNumbers,
    RecipeNumbers,
    build_report,
    change_pct,
    craft_sections,
    gather_sections,
    sell_price,
)
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import GUILD_ID, TEST_API_KEY
from tests.unit.api.conftest import _discord_transport, login_as

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

FEED = "/api/market/feed"
REPORT = "/api/market/report"
BOT_REPORT = f"/api/guilds/{GUILD_ID}/market-report"
BOT = {"X-API-Key": TEST_API_KEY}
FEED_KEY = "market-feed-test-key"
KEYED = {"X-Market-Key": FEED_KEY}

PEACEBLOOM = 2447
KINGSBLOOD = 3356
MITHRIL_ORE = 3858
MITHRIL_BAR = 3860
RUNECLOTH = 14047
GOLDEN_SANSAM = 13464
MOUNTAIN_SILVERSAGE = 13465
CRYSTAL_VIAL = 8925
MAJOR_HEALING = 13446
END = date(2026, 11, 27)
DATA_AT = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)
"""The morning after ``END``: the report's last whole day is ``END``."""


def _item(
    item_id: int,
    name: str,
    *,
    sale: int = 0,
    sold: float = 0.0,
    low: int = 0,
    market: int = 0,
    vendor: int = 0,
    stack: int = 20,
    days: tuple[tuple[date, int, int], ...] = (),
) -> ItemNumbers:
    return ItemNumbers(
        item_id=item_id,
        name=name,
        quality="COMMON",
        stack_size=stack,
        vendor_buy=vendor,
        min_price=low,
        market=market,
        sale_price=sale,
        sold_per_day=sold,
        days=days,
    )


def _flat_days(price: int, count: int = 14, *, last: int | None = None) -> tuple[tuple[date, int, int], ...]:
    """``count`` days of ``price`` ending at ``END``; the last day at ``last`` if given."""
    days = [(END - timedelta(days=offset), price, price) for offset in range(count - 1, -1, -1)]
    if last is not None:
        days[-1] = (END, last, last)
    return tuple(days)


def _potion_market(*, vial_vendor: int = 20, sansam_low: int = 3000, potion_sale: int = 20000) -> dict:
    return {
        MAJOR_HEALING: _item(MAJOR_HEALING, "Major Healing Potion", sale=potion_sale, sold=12, low=21000),
        GOLDEN_SANSAM: _item(GOLDEN_SANSAM, "Golden Sansam", sale=3200, sold=40, low=sansam_low),
        MOUNTAIN_SILVERSAGE: _item(MOUNTAIN_SILVERSAGE, "Mountain Silversage", sale=4000, sold=30, low=4500),
        CRYSTAL_VIAL: _item(CRYSTAL_VIAL, "Crystal Vial", vendor=vial_vendor, low=90),
    }


POTION = RecipeNumbers(
    recipe_id=1,
    name="Major Healing Potion",
    profession="Alchemy",
    crafted_item_id=MAJOR_HEALING,
    crafted_quantity=1,
    reagents=((GOLDEN_SANSAM, 2), (MOUNTAIN_SILVERSAGE, 1), (CRYSTAL_VIAL, 1)),
)


# --- the math -----------------------------------------------------------------------------------------------------


def test_price_is_the_sale_average_but_never_above_the_lowest_listing() -> None:
    assert sell_price(_item(1, "a", sale=500, sold=3, low=400)) == 400
    assert sell_price(_item(1, "a", sale=500, sold=3, low=900)) == 500
    assert sell_price(_item(1, "a", sale=500, sold=3)) == 500, "not listed now: the sale average stands"
    assert sell_price(_item(1, "a", sale=500, sold=0, low=400)) is None, "never sells: no price"
    assert sell_price(_item(1, "a", sale=0, sold=3, low=400)) is None, "no sale record: no price"


def test_gathering_needs_steady_sales_and_ranks_by_price_with_zones_lowest_level_first() -> None:
    items = {
        PEACEBLOOM: _item(PEACEBLOOM, "Peacebloom", sale=40, sold=80),
        KINGSBLOOD: _item(KINGSBLOOD, "Kingsblood", sale=4800, sold=20, low=5000),
        MITHRIL_ORE: _item(MITHRIL_ORE, "Mithril Ore", sale=9000, sold=4),  # 4 a day: a stack would sit for days
        RUNECLOTH: _item(RUNECLOTH, "Runecloth", sale=1500, sold=300),
    }
    sections = {section.profession: section for section in gather_sections(items, "daily", END)}

    assert list(sections) == ["Herbalism", "Mining", "Skinning", "Fishing", "Cloth"]
    herbs = sections["Herbalism"].picks
    assert [pick.item.name for pick in herbs] == ["Kingsblood", "Peacebloom"]
    assert herbs[0].stack_price == 4800 * 20
    assert herbs[0].skill > 0
    zone_levels = [zone.min_level for zone in herbs[0].zones]
    assert zone_levels == sorted(zone_levels)
    assert herbs[0].min_level == zone_levels[0]
    assert sections["Mining"].picks == []
    assert sections["Cloth"].picks[0].skill == 0, "anyone gets cloth from monsters"


def test_a_craft_buys_each_material_where_it_is_cheaper_and_counts_the_cut() -> None:
    sections = craft_sections([POTION], _potion_market(), "daily", END)

    assert [section.profession for section in sections] == ["Alchemy"]
    pick = sections[0].picks[0]
    lines = {line.item.item_id: line for line in pick.reagents}
    assert lines[CRYSTAL_VIAL].from_vendor
    assert lines[CRYSTAL_VIAL].unit_price == 20
    assert not lines[GOLDEN_SANSAM].from_vendor
    assert lines[GOLDEN_SANSAM].unit_price == 3000, "you pay the lowest listing now, not the sale average"
    assert pick.mats_cost == 2 * 3000 + 4500 + 20
    assert pick.profit == int(20000 * 0.95) - pick.mats_cost
    assert pick.margin_pct == round(pick.profit / pick.mats_cost * 100, 1)


def test_crafts_that_lose_money_or_need_an_unbuyable_material_are_left_out() -> None:
    thin = _potion_market(sansam_low=6000)  # 12000 + 4500 + 20 against 19000 after the cut: under 50s profit
    assert craft_sections([POTION], thin, "daily", END) == []

    missing = _potion_market()
    missing[GOLDEN_SANSAM] = _item(GOLDEN_SANSAM, "Golden Sansam", sale=3200, sold=40)  # nobody lists it now
    assert craft_sections([POTION], missing, "daily", END) == []


def test_one_pick_per_crafted_item_and_smelting_is_its_own_section() -> None:
    cheaper = RecipeNumbers(
        recipe_id=2,
        name="Major Healing Potion (old)",
        profession="Alchemy",
        crafted_item_id=MAJOR_HEALING,
        crafted_quantity=1,
        reagents=((GOLDEN_SANSAM, 3), (CRYSTAL_VIAL, 1)),
    )
    smelt = RecipeNumbers(
        recipe_id=3,
        name="Smelt Mithril",
        profession="Mining",
        crafted_item_id=MITHRIL_BAR,
        crafted_quantity=1,
        reagents=((MITHRIL_ORE, 1),),
    )
    items = _potion_market() | {
        MITHRIL_ORE: _item(MITHRIL_ORE, "Mithril Ore", sale=900, sold=50, low=800),
        MITHRIL_BAR: _item(MITHRIL_BAR, "Mithril Bar", sale=7000, sold=30, low=7200),
    }
    sections = {
        section.profession: section for section in craft_sections([POTION, cheaper, smelt], items, "daily", END)
    }

    assert list(sections) == ["Alchemy", "Smelting"]
    assert len(sections["Alchemy"].picks) == 1
    assert sections["Alchemy"].picks[0].recipe_id == 2, "the more profitable way to make the same potion"


def test_daily_change_is_the_latest_day_against_the_week_before_and_needs_history() -> None:
    risen = _item(1, "a", days=_flat_days(1000, last=1200))
    assert change_pct(risen, "daily", END) == 20.0
    assert change_pct(_item(1, "a", days=_flat_days(1000, count=3)), "daily", END) is None


def test_a_cooldown_craft_ranks_by_what_one_craft_a_day_earns() -> None:
    arcanite_bar, thorium_bar, arcane_crystal = 12360, 12359, 12363
    transmute = RecipeNumbers(
        recipe_id=4,
        name="Transmute: Arcanite",
        profession="Alchemy",
        crafted_item_id=arcanite_bar,
        crafted_quantity=1,
        reagents=((thorium_bar, 1), (arcane_crystal, 1)),
    )
    items = _potion_market() | {
        arcanite_bar: _item(arcanite_bar, "Arcanite Bar", sale=170000, sold=200, low=175000),
        thorium_bar: _item(thorium_bar, "Thorium Bar", sale=2500, sold=900, low=2600),
        arcane_crystal: _item(arcane_crystal, "Arcane Crystal", sale=139000, sold=60, low=140000),
    }
    picks = craft_sections([POTION, transmute], items, "daily", END)[0].picks

    assert [pick.item.name for pick in picks] == ["Major Healing Potion", "Arcanite Bar"], (
        "1g89s once every two days earns less a day than 85s on each of 5 potions"
    )
    assert picks[1].cooldown_hours == 48
    assert picks[1].profit > picks[0].profit
    assert picks[0].cooldown_hours is None


def test_weekly_change_compares_this_week_with_last_week() -> None:
    days = tuple((END - timedelta(days=offset), 0, 1000 if offset >= 7 else 900) for offset in range(13, -1, -1))
    assert change_pct(_item(1, "a", days=days), "weekly", END) == -10.0


def test_movers_and_staleness() -> None:
    items = {
        KINGSBLOOD: _item(KINGSBLOOD, "Kingsblood", sale=6000, sold=20, days=_flat_days(5000, last=6000)),
        PEACEBLOOM: _item(PEACEBLOOM, "Peacebloom", sale=60, sold=80, days=_flat_days(30, last=60)),
        MAJOR_HEALING: _item(
            MAJOR_HEALING, "Major Healing Potion", sale=20000, sold=4, days=_flat_days(10000, last=20000)
        ),
        MITHRIL_BAR: _item(
            MITHRIL_BAR, "Iron Counterweight", sale=9000, sold=50, stack=1, days=_flat_days(900, last=9000)
        ),
    }
    made = [
        RecipeNumbers(
            recipe_id=item_id,
            name="x",
            profession="Alchemy",
            crafted_item_id=item_id,
            crafted_quantity=1,
            reagents=((1, 1),),
        )
        for item_id in (MAJOR_HEALING, MITHRIL_BAR)
    ]
    report = build_report(
        "daily",
        house_name="Alliance Auction House 111",
        data_at=DATA_AT,
        items=items,
        recipes=made,
        now=DATA_AT + timedelta(hours=37),
    )

    assert [mover.item.name for mover in report.risers] == ["Kingsblood"], (
        "a 60c item's doubling, 4 potions a day, and one gear listing are all noise"
    )
    assert report.risers[0].profession == "Herbalism"
    assert report.stale
    assert report.period_start == report.period_end == END


# --- the API ------------------------------------------------------------------------------------------------------


def _feed_json(*, snapshot_at: datetime = DATA_AT, extra_item: bool = True) -> dict:
    days = [
        {"day": (END - timedelta(days=offset)).isoformat(), "min_price": 4700, "market": 5000} for offset in range(7)
    ]
    items = [
        {
            "item_id": KINGSBLOOD,
            "name": "Kingsblood",
            "quality": "COMMON",
            "stack_size": 20,
            "min_price": 5000,
            "quantity": 300,
            "market": 5000,
            "sale_price": 4800,
            "sold_per_day": 25.5,
            "days": days,
        }
    ]
    if extra_item:
        items.append(
            {
                "item_id": PEACEBLOOM,
                "name": "Peacebloom",
                "min_price": 40,
                "quantity": 900,
                "market": 45,
                "sale_price": 40,
                "sold_per_day": 90,
            }
        )
    return {
        "house_id": 111,
        "house_name": "Alliance Auction House 111",
        "snapshot_at": snapshot_at.isoformat(),
        "items": items,
        "recipes": [
            {
                "recipe_id": 1,
                "name": "Major Healing Potion",
                "profession": "Alchemy",
                "crafted_item_id": MAJOR_HEALING,
                "reagents": [{"item_id": GOLDEN_SANSAM, "quantity": 2}],
            }
        ],
    }


def _app(database_url: str, web_settings: WebSettings, discord_state: dict) -> Litestar:
    return create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        web_settings,
        discord_transport=_discord_transport(discord_state),
        game_data_transport=httpx.MockTransport(lambda _request: httpx.Response(503, json={"code": 503})),
    )


@pytest.fixture
async def market_client(
    database_url: str, member_web_settings: WebSettings, discord_state: dict
) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """The member app with a market feed key set."""
    settings = member_web_settings.model_copy(update={"MARKET_FEED_KEY": SecretStr(FEED_KEY)})
    async with AsyncTestClient(app=_app(database_url, settings, discord_state)) as client:
        yield client


async def test_feed_needs_the_key_and_is_off_without_one(
    market_client: AsyncTestClient, database_url: str, member_web_settings: WebSettings, discord_state: dict
) -> None:
    assert (await market_client.post(FEED, json=_feed_json())).status_code == 401
    assert (await market_client.post(FEED, json=_feed_json(), headers={"X-Market-Key": "wrong"})).status_code == 401
    async with AsyncTestClient(app=_app(database_url, member_web_settings, discord_state)) as unset:
        assert (await unset.post(FEED, json=_feed_json(), headers=KEYED)).status_code == 503


async def test_report_is_for_guild_members_and_the_bot(market_client: AsyncTestClient, discord_state: dict) -> None:
    assert (await market_client.get(REPORT)).status_code == 401
    await login_as(market_client, discord_state, discord_id=9101, is_guild_member=False)
    assert (await market_client.get(REPORT)).status_code == 403

    await login_as(market_client, discord_state, discord_id=9102)
    before = await market_client.get(REPORT)
    assert before.status_code == 404
    assert before.json()["detail"] == "No market data yet"

    stored = await market_client.post(FEED, json=_feed_json(), headers=KEYED)
    assert stored.status_code == 201, stored.text
    assert stored.json() == {"items": 2, "recipes": 1}

    report = (await market_client.get(REPORT, params={"kind": "weekly"})).json()
    assert report["kind"] == "weekly"
    assert report["house_name"] == "Alliance Auction House 111"
    herbs = next(section for section in report["gathering"] if section["profession"] == "Herbalism")
    assert [pick["item"]["name"] for pick in herbs["picks"]] == ["Kingsblood", "Peacebloom"]
    assert herbs["picks"][0]["sold_per_day"] == 25.5

    assert (await market_client.get(BOT_REPORT, headers=BOT)).status_code == 200
    assert (await market_client.get(f"/api/guilds/{GUILD_ID + 1}/market-report", headers=BOT)).status_code == 404


async def test_a_new_feed_replaces_the_old_one(market_client: AsyncTestClient) -> None:
    await market_client.post(FEED, json=_feed_json(), headers=KEYED)
    later = DATA_AT + timedelta(hours=1)
    await market_client.post(FEED, json=_feed_json(snapshot_at=later, extra_item=False), headers=KEYED)

    report = (await market_client.get(BOT_REPORT, headers=BOT)).json()
    herbs = next(section for section in report["gathering"] if section["profession"] == "Herbalism")
    assert [pick["item"]["name"] for pick in herbs["picks"]] == ["Kingsblood"], "Peacebloom left the feed"
    assert datetime.fromisoformat(report["data_at"]) == later
