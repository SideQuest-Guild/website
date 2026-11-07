"""Auction house prices: the Battle.net sync, public price reads, member price watches, and the alert queue."""

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
lazy from uuid import UUID

from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_409_CONFLICT, HTTP_503_SERVICE_UNAVAILABLE
from sqlalchemy import delete, func, select
from wow import WowError

from sidequest_api.domain.characters.services import ROSTER_GUILD_SLUG
from sidequest_common.models import AuctionAlert as AuctionAlertModel
from sidequest_common.models import AuctionDailyHistory, AuctionHousePriceRow, AuctionHouseState, Member
from sidequest_common.models import AuctionWatch as AuctionWatchModel
from sidequest_common.schemas import (
    AUCTION_ALERT_COOLDOWN_HOURS,
    AUCTION_HISTORY_DAYS,
    AUCTION_TREND_DAYS,
    MAX_AUCTION_WATCHES,
    AuctionAlertSchema,
    AuctionHousePrice,
    AuctionPriceMap,
    AuctionSyncHouse,
    AuctionSyncReport,
    AuctionTrendPoint,
    ItemAuctionPrice,
    ItemPriceSummary,
)
from sidequest_common.schemas import AuctionWatch as AuctionWatchSchema
from sidequest_common.schemas import AuctionWatchCreate as AuctionWatchCreateSchema

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession
    from wow import AsyncClient
    from wow.models.auction import AuctionHouse, CommodityHouse, Ref

    from sidequest_api.domain.items.services import ItemsService

BATTLENET_UNREACHABLE = "Battle.net did not answer; try again in a minute"
FALLBACK_RULESET_ID = 2
FALLBACK_FACTION_TYPE = "ALLIANCE"
FALLBACK_FACTION_NAME = "Alliance"
GUILD_CACHE_SECONDS = 3600
"""The guild's ruleset and faction almost never change: an hour-old answer is as good as a fresh one."""

_guild_cache: tuple[int, str, str, float] | None = None


@dataclass(slots=True)
class _ItemAgg:
    """One item's running cross-house aggregate while a sync is in progress."""

    unit_price: int | None = None
    quantity_total: int = 0
    house_name: str | None = None


@dataclass(slots=True)
class _HouseAgg:
    """One item's aggregate within a single house's listings."""

    unit_price: int
    quantity: int = 0
    listings: int = 0


async def _guild_ruleset_and_faction(game_data: AsyncClient) -> tuple[int, str, str]:
    """The site guild's ``(ruleset_id, faction_type, faction_name)``, cached, falling back to ruleset 2 / Alliance."""
    global _guild_cache  # noqa: PLW0603 - a process-wide cache, like ItemsService's data version
    now = time.monotonic()
    if _guild_cache is not None and now - _guild_cache[3] < GUILD_CACHE_SECONDS:
        return _guild_cache[0], _guild_cache[1], _guild_cache[2]
    try:
        guild = await game_data.guilds.get(ROSTER_GUILD_SLUG)
        result: tuple[int, str, str] = (guild.ruleset.id, guild.faction.type, guild.faction.name)
    except WowError:
        result = (FALLBACK_RULESET_ID, FALLBACK_FACTION_TYPE, FALLBACK_FACTION_NAME)
    _guild_cache = (result[0], result[1], result[2], now)
    return result


def _aggregate_house(house: AuctionHouse, commodities: CommodityHouse) -> dict[int, _HouseAgg]:
    """One house's priced listings folded by item id: lowest unit price, total quantity, listing count.

    Item variants (``bonus_lists``/``modifiers``) are folded into the base item id. Bid-only auctions (no
    ``buyout``) are ignored.
    """
    by_item: dict[int, _HouseAgg] = {}
    for entry in house.auctions:
        if entry.buyout is None:
            continue
        unit_price = entry.buyout // entry.quantity
        agg = by_item.get(entry.item.id)
        if agg is None:
            by_item[entry.item.id] = _HouseAgg(unit_price=unit_price, quantity=entry.quantity, listings=1)
        else:
            agg.unit_price = min(agg.unit_price, unit_price)
            agg.quantity += entry.quantity
            agg.listings += 1
    for commodity in commodities.auctions:
        agg = by_item.get(commodity.item.id)
        if agg is None:
            by_item[commodity.item.id] = _HouseAgg(
                unit_price=commodity.unit_price, quantity=commodity.quantity, listings=1
            )
        else:
            agg.unit_price = min(agg.unit_price, commodity.unit_price)
            agg.quantity += commodity.quantity
            agg.listings += 1
    return by_item


async def _item_info(
    item_id: int, items_service: ItemsService, game_data: AsyncClient
) -> tuple[str | None, str | None]:
    """``(name, icon_url)`` for an item, or ``(None, None)`` if Battle.net doesn't know it or didn't answer."""
    try:
        item = await items_service.get_item(item_id, game_data)
    except NotFoundException, HTTPException:
        return None, None
    return item.name, item.icon_url


class AuctionsService:
    """Reads and writes every auctions table: house prices, daily history, member watches, and queued alerts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- sync (bot) -----------------------------------------------------------------------------------------

    async def sync(self, game_data: AsyncClient, *, now: datetime | None = None) -> AuctionSyncReport:
        """Fetch every house of the guild's faction (sequentially, to bound memory), rebuild prices, queue alerts."""
        reference = now or datetime.now(UTC)
        ruleset_id, _faction_type, faction_name = await _guild_ruleset_and_faction(game_data)
        try:
            index = await game_data.auctions.houses(ruleset_id)
        except WowError as exc:
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
        faction_houses = [house for house in index.auctions if house.name.startswith(faction_name)]

        item_prices: dict[int, _ItemAgg] = {}
        sync_houses = [
            await self._sync_house(game_data, ruleset_id, house_ref, item_prices, reference)
            for house_ref in faction_houses
        ]
        await self._deactivate_stale_houses({house.id for house in faction_houses})
        await self._roll_up_daily_history(item_prices, reference.date())
        alerts_queued = await self._queue_alerts(item_prices, reference)
        return AuctionSyncReport(houses=sync_houses, items_priced=len(item_prices), alerts_queued=alerts_queued)

    async def _sync_house(
        self,
        game_data: AsyncClient,
        ruleset_id: int,
        house_ref: Ref,
        item_prices: dict[int, _ItemAgg],
        reference: datetime,
    ) -> AuctionSyncHouse:
        """Fetch, aggregate and replace one house's current prices in a single transaction."""
        try:
            house = await game_data.auctions.get(ruleset_id, house_ref.id)
            commodities = await game_data.auctions.commodities(ruleset_id, house_ref.id)
        except WowError as exc:
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
        per_item = _aggregate_house(house, commodities)
        session = self._session
        await session.execute(delete(AuctionHousePriceRow).where(AuctionHousePriceRow.house_id == house_ref.id))
        for item_id, agg in per_item.items():
            session.add(
                AuctionHousePriceRow(
                    house_id=house_ref.id,
                    item_id=item_id,
                    house_name=house_ref.name,
                    unit_price=agg.unit_price,
                    quantity=agg.quantity,
                    listings=agg.listings,
                )
            )
            cross = item_prices.setdefault(item_id, _ItemAgg())
            cross.quantity_total += agg.quantity
            if cross.unit_price is None or agg.unit_price < cross.unit_price:
                cross.unit_price = agg.unit_price
                cross.house_name = house_ref.name
        state = (
            await session.execute(select(AuctionHouseState).where(AuctionHouseState.house_id == house_ref.id))
        ).scalar_one_or_none()
        if state is None:
            state = AuctionHouseState(house_id=house_ref.id, house_name=house_ref.name)
            session.add(state)
        state.house_name = house_ref.name
        state.is_active = True
        state.auctions_count = len(house.auctions)
        state.commodities_count = len(commodities.auctions)
        state.last_synced_at = reference
        await session.commit()
        return AuctionSyncHouse(
            house_id=house_ref.id,
            house_name=house_ref.name,
            auctions=len(house.auctions),
            commodities=len(commodities.auctions),
        )

    async def _deactivate_stale_houses(self, active_house_ids: set[int]) -> None:
        """Mark inactive, and prune the prices of, any known house no longer in the faction's current set."""
        session = self._session
        stale = (
            (
                await session.execute(
                    select(AuctionHouseState).where(
                        AuctionHouseState.is_active.is_(True), AuctionHouseState.house_id.not_in(active_house_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for state in stale:
            state.is_active = False
            await session.execute(delete(AuctionHousePriceRow).where(AuctionHousePriceRow.house_id == state.house_id))
        if stale:
            await session.commit()

    async def _roll_up_daily_history(self, item_prices: dict[int, _ItemAgg], today: date) -> None:
        """Keep today's lowest unit price and latest quantity total per item; prune past the retention window."""
        session = self._session
        for item_id, agg in item_prices.items():
            if agg.unit_price is None:
                continue
            row = (
                await session.execute(
                    select(AuctionDailyHistory).where(
                        AuctionDailyHistory.item_id == item_id, AuctionDailyHistory.day == today
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    AuctionDailyHistory(
                        item_id=item_id, day=today, unit_price=agg.unit_price, quantity_total=agg.quantity_total
                    )
                )
            else:
                row.unit_price = min(row.unit_price, agg.unit_price)
                row.quantity_total = agg.quantity_total
        cutoff = today - timedelta(days=AUCTION_HISTORY_DAYS)
        await session.execute(delete(AuctionDailyHistory).where(AuctionDailyHistory.day < cutoff))
        await session.commit()

    async def _queue_alerts(self, item_prices: dict[int, _ItemAgg], reference: datetime) -> int:
        """Queue an alert for every watch whose item's new lowest price is at/below its threshold, past cooldown."""
        session = self._session
        priced_ids = [item_id for item_id, agg in item_prices.items() if agg.unit_price is not None]
        if not priced_ids:
            return 0
        watches = (
            (await session.execute(select(AuctionWatchModel).where(AuctionWatchModel.item_id.in_(priced_ids))))
            .scalars()
            .all()
        )
        if not watches:
            return 0
        member_ids = {watch.member_id for watch in watches}
        members = {
            member.id: member
            for member in (await session.execute(select(Member).where(Member.id.in_(member_ids)))).scalars()
        }
        cooldown = timedelta(hours=AUCTION_ALERT_COOLDOWN_HOURS)
        queued = 0
        for watch in watches:
            agg = item_prices.get(watch.item_id)
            if agg is None or agg.unit_price is None or agg.unit_price > watch.max_unit_price:
                continue
            within_cooldown = watch.last_alerted_at is not None and reference - watch.last_alerted_at < cooldown
            not_lower = watch.last_alerted_price is not None and agg.unit_price >= watch.last_alerted_price
            if within_cooldown and not_lower:
                continue
            member = members.get(watch.member_id)
            if member is None:
                continue
            session.add(
                AuctionAlertModel(
                    watch_id=watch.id,
                    discord_user_id=member.discord_id,
                    member_name=member.display_name,
                    item_id=watch.item_id,
                    unit_price=agg.unit_price,
                    max_unit_price=watch.max_unit_price,
                    quantity=agg.quantity_total,
                    house_name=agg.house_name or "",
                )
            )
            watch.last_alerted_at = reference
            watch.last_alerted_price = agg.unit_price
            queued += 1
        await session.commit()
        return queued

    # --- public price reads -----------------------------------------------------------------------------------

    async def get_item_price(self, item_id: int) -> ItemAuctionPrice:
        """``item_id``'s current price across every house of the guild's faction, plus its trend."""
        session = self._session
        rows = (
            (await session.execute(select(AuctionHousePriceRow).where(AuctionHousePriceRow.item_id == item_id)))
            .scalars()
            .all()
        )
        houses = [
            AuctionHousePrice(
                house_id=row.house_id,
                house_name=row.house_name,
                unit_price=row.unit_price,
                quantity=row.quantity,
                listings=row.listings,
                updated_at=row.updated_at,
            )
            for row in sorted(rows, key=lambda row: row.unit_price)
        ]
        unit_price = min((row.unit_price for row in rows), default=None)
        quantity_total = sum(row.quantity for row in rows)
        updated_at = max((row.updated_at for row in rows), default=None)
        trend = await self._trend(item_id)
        return ItemAuctionPrice(
            item_id=item_id,
            unit_price=unit_price,
            quantity_total=quantity_total,
            houses=houses,
            trend=trend,
            updated_at=updated_at,
        )

    async def _trend(self, item_id: int) -> list[AuctionTrendPoint]:
        """The last ``AUCTION_TREND_DAYS`` days of daily low prices, oldest first."""
        rows = (
            (
                await self._session.execute(
                    select(AuctionDailyHistory)
                    .where(AuctionDailyHistory.item_id == item_id)
                    .order_by(AuctionDailyHistory.day.desc())
                    .limit(AUCTION_TREND_DAYS)
                )
            )
            .scalars()
            .all()
        )
        return [AuctionTrendPoint(day=row.day, unit_price=row.unit_price) for row in reversed(rows)]

    async def get_price_map(self, item_ids: Sequence[int]) -> AuctionPriceMap:
        """One ``ItemPriceSummary`` per requested id, in request order; unpriced ids get null fields."""
        if not item_ids:
            return AuctionPriceMap(prices=[])
        rows = (
            await self._session.execute(
                select(
                    AuctionHousePriceRow.item_id,
                    func.min(AuctionHousePriceRow.unit_price),
                    func.sum(AuctionHousePriceRow.quantity),
                    func.max(AuctionHousePriceRow.updated_at),
                )
                .where(AuctionHousePriceRow.item_id.in_(set(item_ids)))
                .group_by(AuctionHousePriceRow.item_id)
            )
        ).all()
        by_item = {
            item_id: (unit_price, quantity_total, updated_at)
            for item_id, unit_price, quantity_total, updated_at in rows
        }
        prices = []
        for item_id in item_ids:
            unit_price, quantity_total, updated_at = by_item.get(item_id, (None, 0, None))
            prices.append(
                ItemPriceSummary(
                    item_id=item_id, unit_price=unit_price, quantity_total=quantity_total or 0, updated_at=updated_at
                )
            )
        return AuctionPriceMap(prices=prices)

    # --- member price watches ---------------------------------------------------------------------------------

    async def list_watches(
        self, member: Member, items_service: ItemsService, game_data: AsyncClient
    ) -> list[AuctionWatchSchema]:
        """``member``'s price watches, newest first, with each item's current cross-house lowest price."""
        watches = (
            (
                await self._session.execute(
                    select(AuctionWatchModel)
                    .where(AuctionWatchModel.member_id == member.id)
                    .order_by(AuctionWatchModel.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        if not watches:
            return []
        current_prices = await self._current_prices({watch.item_id for watch in watches})
        return [
            await self._to_schema(watch, current_prices.get(watch.item_id), items_service, game_data)
            for watch in watches
        ]

    async def _current_prices(self, item_ids: set[int]) -> dict[int, int]:
        rows = (
            await self._session.execute(
                select(AuctionHousePriceRow.item_id, func.min(AuctionHousePriceRow.unit_price))
                .where(AuctionHousePriceRow.item_id.in_(item_ids))
                .group_by(AuctionHousePriceRow.item_id)
            )
        ).all()
        return {item_id: unit_price for item_id, unit_price in rows}  # noqa: C416 - dict(rows) fails pyrefly's Row overload check

    async def _to_schema(
        self,
        watch: AuctionWatchModel,
        current_unit_price: int | None,
        items_service: ItemsService,
        game_data: AsyncClient,
    ) -> AuctionWatchSchema:
        name, icon_url = await _item_info(watch.item_id, items_service, game_data)
        return AuctionWatchSchema(
            id=watch.id,
            item_id=watch.item_id,
            item_name=name,
            icon_url=icon_url,
            max_unit_price=watch.max_unit_price,
            current_unit_price=current_unit_price,
            created_at=watch.created_at,
            last_alerted_at=watch.last_alerted_at,
        )

    async def save_watch(
        self, member: Member, data: AuctionWatchCreateSchema, items_service: ItemsService, game_data: AsyncClient
    ) -> AuctionWatchSchema:
        """Add ``data.item_id`` to ``member``'s watches, or change its threshold. 409 past ``MAX_AUCTION_WATCHES``."""
        session = self._session
        watch = (
            await session.execute(
                select(AuctionWatchModel).where(
                    AuctionWatchModel.member_id == member.id, AuctionWatchModel.item_id == data.item_id
                )
            )
        ).scalar_one_or_none()
        if watch is None:
            count = (
                await session.execute(
                    select(func.count()).select_from(AuctionWatchModel).where(AuctionWatchModel.member_id == member.id)
                )
            ).scalar_one()
            if count >= MAX_AUCTION_WATCHES:
                msg = f"A member may watch at most {MAX_AUCTION_WATCHES} items; remove one first"
                raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg)
            watch = AuctionWatchModel(member_id=member.id, item_id=data.item_id, max_unit_price=data.max_unit_price)
            session.add(watch)
        else:
            watch.max_unit_price = data.max_unit_price
        await session.commit()
        current_prices = await self._current_prices({data.item_id})
        return await self._to_schema(watch, current_prices.get(data.item_id), items_service, game_data)

    async def delete_watch(self, member: Member, item_id: int) -> None:
        """Remove one of ``member``'s own watches. 404 if there isn't one for ``item_id``."""
        session = self._session
        watch = (
            await session.execute(
                select(AuctionWatchModel).where(
                    AuctionWatchModel.member_id == member.id, AuctionWatchModel.item_id == item_id
                )
            )
        ).scalar_one_or_none()
        if watch is None:
            msg = f"No auction watch for item {item_id}"
            raise NotFoundException(msg)
        await session.delete(watch)
        await session.commit()

    # --- bot alert queue ----------------------------------------------------------------------------------------

    async def pending_alerts(self, items_service: ItemsService, game_data: AsyncClient) -> list[AuctionAlertSchema]:
        """Every unacked alert, oldest first."""
        rows = (
            (
                await self._session.execute(
                    select(AuctionAlertModel)
                    .where(AuctionAlertModel.posted_at.is_(None))
                    .order_by(AuctionAlertModel.created_at)
                )
            )
            .scalars()
            .all()
        )
        result = []
        for row in rows:
            name, icon_url = await _item_info(row.item_id, items_service, game_data)
            result.append(
                AuctionAlertSchema(
                    id=row.id,
                    discord_user_id=row.discord_user_id,
                    member_name=row.member_name,
                    item_id=row.item_id,
                    item_name=name,
                    icon_url=icon_url,
                    unit_price=row.unit_price,
                    max_unit_price=row.max_unit_price,
                    quantity=row.quantity,
                    house_name=row.house_name,
                    created_at=row.created_at,
                )
            )
        return result

    async def mark_alert_sent(self, alert_id: UUID) -> None:
        """Ack one alert so it drops off the pending queue. 404 if it doesn't exist."""
        session = self._session
        row = await session.get(AuctionAlertModel, alert_id)
        if row is None:
            msg = f"No alert {alert_id}"
            raise NotFoundException(msg)
        row.posted_at = datetime.now(UTC)
        await session.commit()
