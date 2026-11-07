"""Auction prices: the Battle.net sync, public price reads, member/bot price watches, the alert queue, and the
``SQI1:`` game-import ``prices`` section. ``local://auctions-contract.md`` is the source of truth."""

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import select
from wow import AsyncClient

from sidequest_api.app import create_app
from sidequest_api.domain.auctions.services import AuctionsService
from sidequest_common.models import (
    AuctionAlert,
    AuctionHousePriceRow,
    AuctionWatch,
    CharacterDirectoryMarket,
    GuildBankLogEntry,
    ItemWish,
    Member,
    ProfessionRecipe,
    WowCharacter,
)
from sidequest_common.schemas import IMPORT_PRICES_LIMIT
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import GUILD_ID, TEST_API_KEY
from tests.unit.api.conftest import OFFICER_ROLE_ID, _discord_transport, login_as
from tests.unit.api.fake_battlenet import (
    battlenet,
    commodity_entry,
    forget_battlenet_state,
    transport,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name

SYNC = f"/api/guilds/{GUILD_ID}/auctions/sync"
BOT = {"X-API-Key": TEST_API_KEY}

# Item ids priced by the default fixture (see fake_battlenet._default_auction_houses):
SINGLE_LISTING = 14559  # house 110 @500, house 111 @450 (cheaper): lowest = 450
QTY_DIVISION = 55555  # house 110 only: buyout 900 // quantity 3 = 300
VARIANT_ITEM = 2079  # house 110 only: two bonus-list variants fold into one id, lowest 550, quantity 3
BID_ONLY = 99999  # house 110 only, no buyout: must never be priced
COMMODITY_ITEM = 2771  # house 110 @2000x17, house 111 @1800x10 (cheaper): lowest = 1800, total qty 27
FOLDED_COMMODITY = 5075  # house 123 only: two commodity rows fold into one id, lowest 545, quantity 19
HORDE_PRICED_ITEM = 7364  # house 123 only (Alliance); also trapped cheap on Horde/Blackwater houses 113/125


@pytest.fixture
async def auctions_client(
    database_url: str, member_web_settings: WebSettings, discord_state: dict, battlenet: dict
) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Member sign-in, the bot key, and the fake Battle.net's ruleset auction houses."""
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        member_web_settings,
        discord_transport=_discord_transport(discord_state),
        game_data_transport=transport(battlenet),
    )
    async with AsyncTestClient(app=app) as client:
        yield client


async def _sync(client: AsyncTestClient) -> dict:
    response = await client.post(SYNC, headers=BOT)
    assert response.status_code == 201, response.text
    return response.json()


async def _price(client: AsyncTestClient, item_id: int) -> dict:
    response = await client.get(f"/api/auctions/prices/{item_id}")
    assert response.status_code == 200, response.text
    return response.json()


# --- aggregation --------------------------------------------------------------------------------------------------


async def test_sync_aggregates_prices_across_faction_houses(auctions_client: AsyncTestClient) -> None:
    report = await _sync(auctions_client)
    house_ids = {house["house_id"] for house in report["houses"]}
    assert house_ids == {110, 111, 112, 119, 123}  # only the guild's faction houses, Horde/Blackwater never fetched
    assert report["items_priced"] == 6  # 14559, 55555, 2079, 2771, 5075, 7364
    assert report["alerts_queued"] == 0

    single = await _price(auctions_client, SINGLE_LISTING)
    assert single["unit_price"] == 450  # lowest of house 110's 500 and house 111's 450
    assert single["quantity_total"] == 2
    by_house = {h["house_id"]: h for h in single["houses"]}
    assert by_house[110]["unit_price"] == 500
    assert by_house[111]["unit_price"] == 450
    assert 113 not in by_house  # Horde house 113 lists this item at 1 copper: never fetched, never priced
    # Five houses share the name "Alliance Auction House"; members tell them apart by the id.
    assert by_house[111]["house_name"] == "Alliance Auction House 111"

    division = await _price(auctions_client, QTY_DIVISION)
    assert division["unit_price"] == 300  # buyout 900 // quantity 3
    assert division["quantity_total"] == 3

    bid_only = await _price(auctions_client, BID_ONLY)
    assert bid_only["unit_price"] is None
    assert bid_only["houses"] == []

    variant = await _price(auctions_client, VARIANT_ITEM)
    assert variant["unit_price"] == 550  # min(1200 // 1, 1100 // 2) across the two bonus-list variants
    assert variant["quantity_total"] == 3  # 1 + 2
    assert variant["houses"][0]["listings"] == 2

    commodity = await _price(auctions_client, COMMODITY_ITEM)
    assert commodity["unit_price"] == 1800  # house 111's commodity price beats house 110's
    assert commodity["quantity_total"] == 27  # 17 + 10

    folded_commodity = await _price(auctions_client, FOLDED_COMMODITY)
    assert folded_commodity["unit_price"] == 545
    assert folded_commodity["quantity_total"] == 19  # 10 + 9
    assert folded_commodity["houses"][0]["listings"] == 2


async def test_horde_and_blackwater_houses_never_affect_alliance_prices(auctions_client: AsyncTestClient) -> None:
    """Houses 113 (Horde) and 125 (Blackwater) list the same items dirt cheap; the sync must never touch them."""
    await _sync(auctions_client)
    price = await _price(auctions_client, HORDE_PRICED_ITEM)
    assert price["unit_price"] == 10000  # the real Alliance (house 123) price, not Horde/Blackwater's 1 copper


async def test_unlisted_item_answers_200_with_null_price(auctions_client: AsyncTestClient) -> None:
    await _sync(auctions_client)
    price = await _price(auctions_client, 7654321)
    assert price == {
        "item_id": 7654321,
        "unit_price": None,
        "quantity_total": 0,
        "houses": [],
        "trend": [],
        "updated_at": None,
    }


async def test_resync_replaces_a_houses_rows_and_drops_items_that_disappeared(
    auctions_client: AsyncTestClient, battlenet: dict
) -> None:
    await _sync(auctions_client)
    assert (await _price(auctions_client, QTY_DIVISION))["unit_price"] == 300

    # House 110 no longer lists the quantity-division item on the next sweep.
    battlenet["auction_houses"][110]["auctions"] = [
        entry for entry in battlenet["auction_houses"][110]["auctions"] if entry["item"]["id"] != QTY_DIVISION
    ]
    await _sync(auctions_client)

    gone = await _price(auctions_client, QTY_DIVISION)
    assert gone["unit_price"] is None
    assert gone["houses"] == []
    # Other house-110 items the house still lists come through fine.
    assert (await _price(auctions_client, SINGLE_LISTING))["unit_price"] == 450


# --- price routes --------------------------------------------------------------------------------------------------


async def test_price_map_returns_one_entry_per_id_in_request_order(auctions_client: AsyncTestClient) -> None:
    await _sync(auctions_client)
    response = await auctions_client.get(f"/api/auctions/prices?ids={VARIANT_ITEM},7654321,{COMMODITY_ITEM}")
    assert response.status_code == 200, response.text
    prices = response.json()["prices"]
    assert [p["item_id"] for p in prices] == [VARIANT_ITEM, 7654321, COMMODITY_ITEM]
    assert prices[0]["unit_price"] == 550
    assert prices[1] == {"item_id": 7654321, "unit_price": None, "quantity_total": 0, "updated_at": None}
    assert prices[2]["unit_price"] == 1800


async def test_price_map_rejects_zero_ids(auctions_client: AsyncTestClient) -> None:
    response = await auctions_client.get("/api/auctions/prices?ids=")
    assert response.status_code == 400


async def test_price_map_rejects_too_many_ids(auctions_client: AsyncTestClient) -> None:
    ids = ",".join(str(i) for i in range(1, 202))  # 201 > MAX_PRICE_IDS (200)
    response = await auctions_client.get(f"/api/auctions/prices?ids={ids}")
    assert response.status_code == 400


# --- /api/me watch CRUD ----------------------------------------------------------------------------------------


async def test_member_watch_crud(auctions_client: AsyncTestClient, discord_state: dict, battlenet: dict) -> None:
    battlenet["items"][SINGLE_LISTING] = "Worn Shortsword"
    await _sync(auctions_client)
    await login_as(auctions_client, discord_state, discord_id=8001)

    listed = await auctions_client.get("/api/me/auction-watches")
    assert listed.status_code == 200, listed.text
    assert listed.json() == []

    created = await auctions_client.post(
        "/api/me/auction-watches", json={"item_id": SINGLE_LISTING, "max_unit_price": 1000}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["item_id"] == SINGLE_LISTING
    assert body["item_name"] == "Worn Shortsword"
    assert body["max_unit_price"] == 1000
    assert body["current_unit_price"] == 450

    # posting again for the same item upserts the threshold, not a new row.
    updated = await auctions_client.post(
        "/api/me/auction-watches", json={"item_id": SINGLE_LISTING, "max_unit_price": 200}
    )
    assert updated.status_code == 201, updated.text
    assert updated.json()["max_unit_price"] == 200
    listed_again = await auctions_client.get("/api/me/auction-watches")
    assert len(listed_again.json()) == 1

    deleted = await auctions_client.delete(f"/api/me/auction-watches/{SINGLE_LISTING}")
    assert deleted.status_code == 204
    assert (await auctions_client.get("/api/me/auction-watches")).json() == []


async def test_delete_watch_404_when_none_exists(auctions_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(auctions_client, discord_state, discord_id=8002)
    response = await auctions_client.delete(f"/api/me/auction-watches/{SINGLE_LISTING}")
    assert response.status_code == 404


async def test_member_watch_409_at_cap(auctions_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(auctions_client, discord_state, discord_id=8003)
    for item_id in range(1, 26):  # MAX_AUCTION_WATCHES = 25
        response = await auctions_client.post(
            "/api/me/auction-watches", json={"item_id": item_id, "max_unit_price": 100}
        )
        assert response.status_code == 201, response.text
    over_cap = await auctions_client.post("/api/me/auction-watches", json={"item_id": 9999, "max_unit_price": 100})
    assert over_cap.status_code == 409


async def test_member_watch_requires_sign_in(auctions_client: AsyncTestClient) -> None:
    response = await auctions_client.get("/api/me/auction-watches")
    assert response.status_code == 401


# --- bot watch routes -------------------------------------------------------------------------------------------


async def test_bot_watch_routes_404_for_unlinked_discord_user(auctions_client: AsyncTestClient) -> None:
    response = await auctions_client.get(f"/api/guilds/{GUILD_ID}/members/424242/auction-watches", headers=BOT)
    assert response.status_code == 404
    assert "Discord account on the site" in response.text


async def test_bot_watch_routes_work_for_a_linked_member(auctions_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(auctions_client, discord_state, discord_id=8004)

    created = await auctions_client.post(
        f"/api/guilds/{GUILD_ID}/members/8004/auction-watches",
        json={"item_id": SINGLE_LISTING, "max_unit_price": 1000},
        headers=BOT,
    )
    assert created.status_code == 201, created.text

    listed = await auctions_client.get(f"/api/guilds/{GUILD_ID}/members/8004/auction-watches", headers=BOT)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1

    deleted = await auctions_client.delete(
        f"/api/guilds/{GUILD_ID}/members/8004/auction-watches/{SINGLE_LISTING}", headers=BOT
    )
    assert deleted.status_code == 204


# --- sync edge cases --------------------------------------------------------------------------------------------


async def test_sync_404_for_another_guild(auctions_client: AsyncTestClient) -> None:
    response = await auctions_client.post(f"/api/guilds/{GUILD_ID + 1}/auctions/sync", headers=BOT)
    assert response.status_code == 404


async def test_battlenet_503_during_sync_is_a_clean_error_and_keeps_stored_prices(
    auctions_client: AsyncTestClient, battlenet: dict
) -> None:
    await _sync(auctions_client)
    assert (await _price(auctions_client, SINGLE_LISTING))["unit_price"] == 450

    battlenet["down"] = True
    response = await auctions_client.post(SYNC, headers=BOT)
    assert response.status_code == 503
    assert response.status_code != 500

    # The previously-synced price is untouched by the failed attempt.
    assert (await _price(auctions_client, SINGLE_LISTING))["unit_price"] == 450


# --- daily history and trend ------------------------------------------------------------------------------------


async def test_daily_history_keeps_lowest_price_and_trend_shows_last_14_days(
    database_url: str, battlenet: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    item_id = 909090
    base = datetime(2026, 1, 1, tzinfo=UTC)
    async with httpx.AsyncClient(transport=transport(battlenet)) as http:
        game_data = AsyncClient("bnet-id", "bnet-secret", http_client=http)
        for day in range(20):
            battlenet["auction_houses"][110]["commodities"] = [
                commodity_entry(item_id, unit_price=1000 - day, quantity=5, entry_id=item_id * 10 + day)
            ]
            async with db_sessionmaker() as session:
                await AuctionsService(session).sync(game_data, now=base + timedelta(days=day))

        async with db_sessionmaker() as session:
            price = await AuctionsService(session).get_item_price(item_id)

    assert len(price.trend) == 14  # AUCTION_TREND_DAYS, out of 20 days synced
    assert price.trend[0].day == (base + timedelta(days=6)).date()
    assert price.trend[0].unit_price == 994
    assert price.trend[-1].day == (base + timedelta(days=19)).date()
    assert price.trend[-1].unit_price == 981
    assert [point.unit_price for point in price.trend] == list(range(994, 980, -1))


# --- alert rules -------------------------------------------------------------------------------------------------


async def test_alerts_queue_respect_cooldown_and_relower(
    battlenet: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    item_id = 424242
    async with db_sessionmaker() as session:
        member = Member(discord_id=8101, username="watcher", is_guild_member=True)
        session.add(member)
        await session.flush()
        watch = AuctionWatch(member_id=member.id, item_id=item_id, max_unit_price=500)
        session.add(watch)
        await session.commit()
        watch_id = watch.id

    base = datetime(2026, 3, 1, tzinfo=UTC)
    async with httpx.AsyncClient(transport=transport(battlenet)) as http:
        game_data = AsyncClient("bnet-id", "bnet-secret", http_client=http)

        async def sync_at(price: int, when: datetime) -> int:
            battlenet["auction_houses"][110]["commodities"] = [commodity_entry(item_id, unit_price=price, quantity=1)]
            async with db_sessionmaker() as session:
                report = await AuctionsService(session).sync(game_data, now=when)
            return report.alerts_queued

        # Price at/below max: queues one alert.
        assert await sync_at(400, base) == 1
        # Same price, within the 24h cooldown: no new alert.
        assert await sync_at(400, base + timedelta(hours=1)) == 0
        # Lower price, still within cooldown: re-alerts.
        assert await sync_at(350, base + timedelta(hours=2)) == 1
        # Above max: never alerts.
        assert await sync_at(600, base + timedelta(hours=3)) == 0

    async with db_sessionmaker() as session:
        alerts = (
            (
                await session.execute(
                    select(AuctionAlert).where(AuctionAlert.watch_id == watch_id).order_by(AuctionAlert.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert [alert.unit_price for alert in alerts] == [400, 350]


# --- pending alerts and ack --------------------------------------------------------------------------------------


async def test_pending_alerts_oldest_first_and_ack(
    auctions_client: AsyncTestClient, discord_state: dict, battlenet: dict
) -> None:
    await login_as(auctions_client, discord_state, discord_id=8201)
    watch_a = await auctions_client.post(
        "/api/me/auction-watches", json={"item_id": SINGLE_LISTING, "max_unit_price": 1000}
    )
    assert watch_a.status_code == 201, watch_a.text
    first_report = await _sync(auctions_client)  # item 14559 is already priced at 450: queues immediately
    assert first_report["alerts_queued"] == 1

    second_item = 313131
    battlenet["auction_houses"][111]["commodities"].append(commodity_entry(second_item, unit_price=200, quantity=3))
    watch_b = await auctions_client.post(
        "/api/me/auction-watches", json={"item_id": second_item, "max_unit_price": 1000}
    )
    assert watch_b.status_code == 201, watch_b.text
    second_report = await _sync(auctions_client)
    assert second_report["alerts_queued"] == 1

    pending = await auctions_client.get(f"/api/guilds/{GUILD_ID}/auctions/alerts/pending", headers=BOT)
    assert pending.status_code == 200, pending.text
    alerts = pending.json()
    assert [alert["item_id"] for alert in alerts] == [SINGLE_LISTING, second_item]

    ack = await auctions_client.post(f"/api/guilds/{GUILD_ID}/auctions/alerts/{alerts[0]['id']}/sent", headers=BOT)
    assert ack.status_code == 204

    remaining = await auctions_client.get(f"/api/guilds/{GUILD_ID}/auctions/alerts/pending", headers=BOT)
    assert [alert["item_id"] for alert in remaining.json()] == [second_item]


# --- game import prices -----------------------------------------------------------------------------------------


async def _officer_member_id(client: AsyncTestClient, discord_state: dict, discord_id: int) -> int:
    await login_as(client, discord_state, discord_id=discord_id, roles=[OFFICER_ROLE_ID])
    return (await client.get("/api/me")).json()["id"]


async def _decode_game_import(client: AsyncTestClient) -> dict:
    response = await client.get("/api/epgp/game-import")
    assert response.status_code == 200, response.text
    return json.loads(base64.b64decode(response.json()["payload"][len("SQI1:") :]))


async def test_game_import_prices_covers_every_source_and_skips_unpriced_items(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    sell_item, buy_item, request_item = 11111, 22222, 33333
    wish_item, bank_item, recipe_item = 44444, 55554, 66666
    unpriced_item = 77777

    member_id = await _officer_member_id(member_client, discord_state, 8301)
    async with db_sessionmaker() as session:
        character = WowCharacter(name="Pricer", realm="Whitemane", key="pricer-whitemane")
        session.add(character)
        await session.flush()
        session.add(
            CharacterDirectoryMarket(
                character_id=character.id,
                sell=[{"item_id": sell_item, "price": 100, "qty": 1, "crafted": False}],
                buy=[{"item_id": buy_item, "price": 50}],
                requests=[{"id": "r1", "item_id": request_item, "qty": 2, "price": None, "note": None, "at": 0}],
            )
        )
        session.add(ItemWish(member_id=member_id, item_id=wish_item))
        session.add(
            GuildBankLogEntry(
                external_id="bank-1", at=datetime.now(UTC), kind="deposit", item_id=bank_item, count=1, money=0
            )
        )
        session.add(ProfessionRecipe(recipe_id=1, name="Flask Recipe", item_id=recipe_item))
        session.add(ProfessionRecipe(recipe_id=2, name="No Item Recipe", item_id=None))
        priced_at = datetime(2026, 4, 1, tzinfo=UTC)
        for item_id, unit_price, quantity in (
            (sell_item, 1000, 5),
            (buy_item, 2000, 3),
            (request_item, 3000, 1),
            (wish_item, 4000, 2),
            (bank_item, 5000, 1),
            (recipe_item, 6000, 4),
        ):
            session.add(
                AuctionHousePriceRow(
                    house_id=110,
                    item_id=item_id,
                    house_name="Alliance Auction House",
                    unit_price=unit_price,
                    quantity=quantity,
                    listings=1,
                    updated_at=priced_at,
                )
            )
        # A second, cheaper house row for sell_item: the price should pick the lowest and sum quantity.
        session.add(
            AuctionHousePriceRow(
                house_id=111,
                item_id=sell_item,
                house_name="Alliance Auction House",
                unit_price=800,
                quantity=2,
                listings=1,
                updated_at=priced_at,
            )
        )
        # unpriced_item is traded (on the wishlist) but has no stored price row: must be excluded.
        session.add(ItemWish(member_id=member_id, item_id=unpriced_item))
        await session.commit()

    decoded = await _decode_game_import(member_client)
    by_item = {row["item_id"]: row for row in decoded["prices"]}
    assert set(by_item) == {sell_item, buy_item, request_item, wish_item, bank_item, recipe_item}
    assert by_item[sell_item]["unit_price"] == 800  # lowest across the two house rows
    assert by_item[sell_item]["quantity"] == 7  # 5 + 2
    assert by_item[sell_item]["at"] == int(priced_at.timestamp())
    assert by_item[buy_item]["unit_price"] == 2000
    assert by_item[request_item]["unit_price"] == 3000
    assert by_item[wish_item]["unit_price"] == 4000
    assert by_item[bank_item]["unit_price"] == 5000
    assert by_item[recipe_item]["unit_price"] == 6000


async def test_game_import_prices_capped_at_import_prices_limit(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _officer_member_id(member_client, discord_state, 8302)
    extra = 10
    async with db_sessionmaker() as session:
        for item_id in range(100000, 100000 + IMPORT_PRICES_LIMIT + extra):
            session.add(ItemWish(member_id=member_id, item_id=item_id))
            session.add(
                AuctionHousePriceRow(
                    house_id=110,
                    item_id=item_id,
                    house_name="Alliance Auction House",
                    unit_price=100,
                    quantity=1,
                    listings=1,
                )
            )
        await session.commit()

    decoded = await _decode_game_import(member_client)
    assert len(decoded["prices"]) == IMPORT_PRICES_LIMIT
