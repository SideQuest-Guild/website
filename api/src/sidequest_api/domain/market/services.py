"""The market report's storage: keep the latest feed per house, and build the report from it."""

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from sidequest_api.domain.market.report import ItemNumbers, RecipeNumbers, build_report, is_stale
from sidequest_common.models import MarketFeedState, MarketItem, MarketRecipe
from sidequest_common.schemas import MarketFeed, MarketFeedItem, MarketFeedReceipt, MarketReport, MarketReportKind

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_cache: dict[tuple[int, MarketReportKind], tuple[datetime, MarketReport]] = {}
"""Built reports by ``(house_id, kind)``, kept while the house's feed is unchanged (its ``received_at``)."""


def _item_numbers(row: MarketItem) -> ItemNumbers:
    return ItemNumbers(
        item_id=row.item_id,
        name=row.name,
        quality=row.quality,
        stack_size=row.stack_size,
        vendor_buy=row.vendor_buy,
        min_price=row.min_price,
        market=row.market,
        sale_price=row.sale_price,
        sold_per_day=row.sold_per_day,
        days=tuple((date.fromisoformat(day), int(low), int(market)) for day, low, market in row.days),
    )


def _recipe_numbers(row: MarketRecipe) -> RecipeNumbers:
    return RecipeNumbers(
        recipe_id=row.recipe_id,
        name=row.name,
        profession=row.profession,
        crafted_item_id=row.crafted_item_id,
        crafted_quantity=row.crafted_quantity,
        reagents=tuple((int(item_id), int(quantity)) for item_id, quantity in row.reagents),
    )


def _days_json(item: MarketFeedItem) -> list[list[str | int]]:
    return [[day.day.isoformat(), day.min_price, day.market] for day in sorted(item.days, key=lambda d: d.day)]


class MarketService:
    """Stores the market feed and serves the report built from it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def store_feed(self, feed: MarketFeed, *, now: datetime | None = None) -> MarketFeedReceipt:
        """Replace the house's items and recipes with the feed's, in one transaction. Duplicate IDs: last wins."""
        received_at = now or datetime.now(UTC)
        items = {item.item_id: item for item in feed.items}
        recipes = {recipe.recipe_id: recipe for recipe in feed.recipes}
        session = self._session
        await session.execute(delete(MarketItem).where(MarketItem.house_id == feed.house_id))
        await session.execute(delete(MarketRecipe).where(MarketRecipe.house_id == feed.house_id))
        session.add_all(
            MarketItem(
                house_id=feed.house_id,
                item_id=item.item_id,
                name=item.name,
                quality=item.quality,
                stack_size=item.stack_size,
                vendor_buy=item.vendor_buy,
                vendor_sell=item.vendor_sell,
                min_price=item.min_price,
                quantity=item.quantity,
                market=item.market,
                sale_price=item.sale_price,
                sold_per_day=item.sold_per_day,
                days=[
                    [day.day.isoformat(), day.min_price, day.market] for day in sorted(item.days, key=lambda d: d.day)
                ],
            )
            for item in items.values()
        )
        session.add_all(
            MarketRecipe(
                house_id=feed.house_id,
                recipe_id=recipe.recipe_id,
                name=recipe.name,
                profession=recipe.profession,
                crafted_item_id=recipe.crafted_item_id,
                crafted_quantity=recipe.crafted_quantity,
                reagents=[[reagent.item_id, reagent.quantity] for reagent in recipe.reagents],
            )
            for recipe in recipes.values()
        )
        state = (
            await session.execute(select(MarketFeedState).where(MarketFeedState.house_id == feed.house_id))
        ).scalar_one_or_none()
        if state is None:
            state = MarketFeedState(house_id=feed.house_id)
            session.add(state)
        state.house_name = feed.house_name
        state.snapshot_at = feed.snapshot_at
        state.received_at = received_at
        state.items = len(items)
        state.recipes = len(recipes)
        await session.commit()
        return MarketFeedReceipt(items=len(items), recipes=len(recipes))

    async def report(self, kind: MarketReportKind, *, now: datetime | None = None) -> MarketReport | None:
        """The report from the most recently fed house, or ``None`` before any feed."""
        moment = now or datetime.now(UTC)
        session = self._session
        state = (
            await session.execute(select(MarketFeedState).order_by(MarketFeedState.received_at.desc()).limit(1))
        ).scalar_one_or_none()
        if state is None:
            return None
        key = (state.house_id, kind)
        cached = _cache.get(key)
        if cached is not None and cached[0] == state.received_at:
            return cached[1].model_copy(update={"stale": is_stale(cached[1].data_at, moment)})
        item_rows = (await session.execute(select(MarketItem).where(MarketItem.house_id == state.house_id))).scalars()
        recipe_rows = (
            await session.execute(select(MarketRecipe).where(MarketRecipe.house_id == state.house_id))
        ).scalars()
        items = {row.item_id: _item_numbers(row) for row in item_rows}
        recipes = [_recipe_numbers(row) for row in recipe_rows]
        report = build_report(
            kind, house_name=state.house_name, data_at=state.snapshot_at, items=items, recipes=recipes, now=moment
        )
        _cache[key] = (state.received_at, report)
        return report
