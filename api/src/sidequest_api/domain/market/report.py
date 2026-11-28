"""The market report's math: turn one house's feed into the best materials to gather and crafts to make.

Pure functions over plain data, so the rules are tested without a database. The report never names a listing or a
resale deal: it only says what a material or a crafted item really sells for, how many sell a day, and, for crafts,
what the materials cost to buy now.

Rules (the shared contract):

- An item's price is what it really sold for over 14 days, but no more than the lowest listing now: a seller has to
  match that listing to sell today.
- A material qualifies at ``GATHER_MIN_SOLD`` sold a day, so a farmed stack sells within a few days. Ranked by price.
- A craft qualifies at ``CRAFT_MIN_SOLD`` sold a day, ``CRAFT_MIN_PROFIT`` profit and ``CRAFT_MIN_MARGIN`` percent
  over the materials. Materials cost the cheaper of a vendor and the lowest listing now; a material nobody sells
  makes the craft unbuyable, so it's left out. Ranked by profit times sold a day, capped at ``CRAFT_DEMAND_CAP``,
  so a fat margin nobody buys doesn't outrank a steady seller.
- A recipe on a cooldown (transmutes, Mooncloth) can only be made once per cooldown, so its demand in the ranking is
  capped at crafts a day as well.
- Movers need ``MOVER_MIN_SOLD`` sold a day and must stack: a thin item's one odd sale, or one new gear listing, is
  not a market move.
- Changes and charts use whole UTC days only, up to the day before the data was taken.
- The daily change compares the latest day with the median of the 7 days before it; the weekly change compares the
  mean of the last 7 days with the 7 before. Each side needs ``MIN_CHANGE_POINTS`` days of data.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import mean, median
from typing import TYPE_CHECKING

from sidequest_api.domain.market.gathering import GATHER_PROFESSIONS, GATHERED, ZONE_LEVELS
from sidequest_common.schemas import (
    MARKET_AH_CUT,
    MARKET_STALE_HOURS,
    MarketCraftPick,
    MarketCraftSection,
    MarketGatherPick,
    MarketGatherSection,
    MarketItemRef,
    MarketMover,
    MarketPoint,
    MarketReagentLine,
    MarketReport,
    MarketReportKind,
    MarketZone,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

GATHER_MIN_SOLD = 5.0
CRAFT_MIN_SOLD = 1.0
CRAFT_MIN_PROFIT = 5000
"""50 silver a craft."""
CRAFT_MIN_MARGIN = 10.0
CRAFT_DEMAND_CAP = 5.0
PICKS_PER_SECTION = 12
MOVERS = 5
MOVER_MIN_CHANGE = 10.0
MOVER_MIN_SOLD = 10.0
MOVER_MIN_PRICE = 500
"""5 silver: a copper item's 30% swing is noise."""
MIN_CHANGE_POINTS = 3
TREND_DAYS: dict[str, int] = {"daily": 14, "weekly": 30}
COOLDOWN_HOURS: dict[str, float] = {"Mooncloth": 96.0, "Transmute: Arcanite": 48.0}
"""Recipes made once per cooldown, by exact name; every other ``Transmute: `` recipe is ``TRANSMUTE_HOURS``."""
TRANSMUTE_PREFIX = "Transmute: "
TRANSMUTE_HOURS = 24.0
CRAFT_SECTION_NAMES: dict[str, str] = {"Mining": "Smelting"}
"""Mining's recipes are smelting; the gathering side keeps the name Mining."""


@dataclass(frozen=True, slots=True)
class ItemNumbers:
    """One item's feed numbers. ``days`` holds ``(day, min_price, market)``, oldest first."""

    item_id: int
    name: str
    quality: str | None
    stack_size: int
    vendor_buy: int
    min_price: int
    market: int
    sale_price: int
    sold_per_day: float
    days: tuple[tuple[date, int, int], ...]


@dataclass(frozen=True, slots=True)
class RecipeNumbers:
    """One recipe from the feed. ``reagents`` holds ``(item_id, quantity)``."""

    recipe_id: int
    name: str
    profession: str
    crafted_item_id: int
    crafted_quantity: float
    reagents: tuple[tuple[int, int], ...]


def cooldown_hours(recipe_name: str) -> float | None:
    """Hours before ``recipe_name`` can be made again, or ``None`` if it has no cooldown."""
    if recipe_name in COOLDOWN_HOURS:
        return COOLDOWN_HOURS[recipe_name]
    return TRANSMUTE_HOURS if recipe_name.startswith(TRANSMUTE_PREFIX) else None


def sell_price(item: ItemNumbers) -> int | None:
    """What one really sells for now, or ``None`` without sales: the sale average, capped at the lowest listing."""
    if item.sale_price <= 0 or item.sold_per_day <= 0:
        return None
    if item.min_price > 0:
        return min(item.sale_price, item.min_price)
    return item.sale_price


def _ref(item: ItemNumbers) -> MarketItemRef:
    return MarketItemRef(item_id=item.item_id, name=item.name, quality=item.quality)


def _zone(name: str) -> MarketZone:
    low, high = ZONE_LEVELS[name]
    return MarketZone(name=name, min_level=low, max_level=high)


def _priced_days(item: ItemNumbers) -> list[tuple[date, int]]:
    return [(day, market) for day, _low, market in item.days if market > 0]


def trend(item: ItemNumbers, end: date, days: int) -> list[MarketPoint]:
    """Daily typical prices in the ``days`` up to ``end``, oldest first."""
    start = end - timedelta(days=days - 1)
    return [MarketPoint(day=day, price=price) for day, price in _priced_days(item) if start <= day <= end]


def change_pct(item: ItemNumbers, kind: MarketReportKind, end: date) -> float | None:
    """Price change in percent against the period before (see the module rules), or ``None`` without enough data."""
    priced = [(day, price) for day, price in _priced_days(item) if day <= end]
    if not priced:
        return None
    if kind == "daily":
        latest_day, latest = priced[-1]
        base_values = [p for d, p in priced if latest_day - timedelta(days=7) <= d < latest_day]
        if len(base_values) < MIN_CHANGE_POINTS:
            return None
        now, base = float(latest), float(median(base_values))
    else:
        recent = [p for d, p in priced if end - timedelta(days=7) < d <= end]
        before = [p for d, p in priced if end - timedelta(days=14) < d <= end - timedelta(days=7)]
        if len(recent) < MIN_CHANGE_POINTS or len(before) < MIN_CHANGE_POINTS:
            return None
        now, base = mean(recent), mean(before)
    if base <= 0:
        return None
    return round((now - base) / base * 100, 1)


def gather_sections(items: Mapping[int, ItemNumbers], kind: MarketReportKind, end: date) -> list[MarketGatherSection]:
    """The best materials for each gathering profession, in ``GATHER_PROFESSIONS`` order."""
    by_profession: dict[str, list[MarketGatherPick]] = {name: [] for name in GATHER_PROFESSIONS}
    for item_id, gathered in GATHERED.items():
        item = items.get(item_id)
        if item is None or item.sold_per_day < GATHER_MIN_SOLD:
            continue
        price = sell_price(item)
        if price is None:
            continue
        zones = sorted(
            (
                MarketZone(name=zone, min_level=ZONE_LEVELS[zone][0], max_level=ZONE_LEVELS[zone][1])
                for zone in gathered.zones
            ),
            key=lambda zone: (zone.min_level, zone.max_level, zone.name),
        )
        stack = max(item.stack_size, 1)
        by_profession[gathered.profession].append(
            MarketGatherPick(
                item=_ref(item),
                price=price,
                stack_size=stack,
                stack_price=price * stack,
                sold_per_day=round(item.sold_per_day, 1),
                change_pct=change_pct(item, kind, end),
                skill=gathered.skill,
                min_level=min((zone.min_level for zone in zones), default=1),
                max_level=max((zone.max_level for zone in zones), default=60),
                zones=zones,
                trend=trend(item, end, TREND_DAYS[kind]),
            )
        )
    return [
        MarketGatherSection(
            profession=name,
            picks=sorted(picks, key=lambda pick: (-pick.price, pick.item.name))[:PICKS_PER_SECTION],
        )
        for name, picks in by_profession.items()
    ]


def _reagent_line(item: ItemNumbers, quantity: int) -> MarketReagentLine | None:
    """One material at the cheaper of a vendor and the lowest listing now; ``None`` if nobody sells it."""
    listed = item.min_price if item.min_price > 0 else None
    vendor = item.vendor_buy if item.vendor_buy > 0 else None
    if listed is None and vendor is None:
        return None
    from_vendor = vendor is not None and (listed is None or vendor <= listed)
    unit = vendor if from_vendor and vendor is not None else listed
    if unit is None:
        return None
    return MarketReagentLine(item=_ref(item), quantity=quantity, unit_price=unit, from_vendor=from_vendor)


def craft_pick(
    recipe: RecipeNumbers, items: Mapping[int, ItemNumbers], kind: MarketReportKind, end: date
) -> MarketCraftPick | None:
    """The recipe as a craft worth making, or ``None`` if it fails any of the module's craft rules."""
    product = items.get(recipe.crafted_item_id)
    if product is None or product.sold_per_day < CRAFT_MIN_SOLD:
        return None
    price = sell_price(product)
    if price is None:
        return None
    lines: list[MarketReagentLine] = []
    for reagent_id, quantity in recipe.reagents:
        reagent = items.get(reagent_id)
        line = _reagent_line(reagent, quantity) if reagent is not None else None
        if line is None:
            return None
        lines.append(line)
    mats_cost = sum(line.unit_price * line.quantity for line in lines)
    if mats_cost <= 0:
        return None
    profit = int(price * recipe.crafted_quantity * (1 - MARKET_AH_CUT) - mats_cost)
    margin = profit / mats_cost * 100
    if profit < CRAFT_MIN_PROFIT or margin < CRAFT_MIN_MARGIN:
        return None
    return MarketCraftPick(
        recipe_id=recipe.recipe_id,
        recipe_name=recipe.name,
        item=_ref(product),
        makes=recipe.crafted_quantity,
        price=price,
        mats_cost=mats_cost,
        profit=profit,
        margin_pct=round(margin, 1),
        sold_per_day=round(product.sold_per_day, 1),
        change_pct=change_pct(product, kind, end),
        cooldown_hours=cooldown_hours(recipe.name),
        reagents=lines,
        trend=trend(product, end, TREND_DAYS[kind]),
    )


def _craft_score(pick: MarketCraftPick) -> float:
    demand = min(pick.sold_per_day, CRAFT_DEMAND_CAP)
    if pick.cooldown_hours:
        demand = min(demand, 24 / pick.cooldown_hours)
    return pick.profit * demand


def craft_sections(
    recipes: Iterable[RecipeNumbers], items: Mapping[int, ItemNumbers], kind: MarketReportKind, end: date
) -> list[MarketCraftSection]:
    """The best crafts for each crafting profession that has any, by profession name; one pick per crafted item."""
    best: dict[tuple[str, int], MarketCraftPick] = {}
    for recipe in recipes:
        pick = craft_pick(recipe, items, kind, end)
        if pick is None:
            continue
        section = CRAFT_SECTION_NAMES.get(recipe.profession, recipe.profession)
        key = (section, pick.item.item_id)
        if key not in best or _craft_score(pick) > _craft_score(best[key]):
            best[key] = pick
    by_section: dict[str, list[MarketCraftPick]] = {}
    for (section, _item_id), pick in best.items():
        by_section.setdefault(section, []).append(pick)
    return [
        MarketCraftSection(
            profession=section,
            picks=sorted(picks, key=lambda pick: (-_craft_score(pick), pick.item.name))[:PICKS_PER_SECTION],
        )
        for section, picks in sorted(by_section.items())
    ]


def movers(
    items: Mapping[int, ItemNumbers], recipes: Sequence[RecipeNumbers], kind: MarketReportKind, end: date
) -> tuple[list[MarketMover], list[MarketMover]]:
    """The biggest risers and fallers among materials and crafts that sell, ``MOVERS`` each."""
    professions: dict[int, str] = {}
    for recipe in recipes:
        professions.setdefault(recipe.crafted_item_id, CRAFT_SECTION_NAMES.get(recipe.profession, recipe.profession))
    for item_id, gathered in GATHERED.items():
        professions[item_id] = gathered.profession
    moved: list[MarketMover] = []
    for item_id, profession in professions.items():
        item = items.get(item_id)
        # Gear (stacks of 1) has a few listings each at its own price, so one new listing swings its daily price.
        if item is None or item.stack_size <= 1 or item.sold_per_day < MOVER_MIN_SOLD:
            continue
        price = sell_price(item)
        change = change_pct(item, kind, end)
        if price is None or change is None or price < MOVER_MIN_PRICE or abs(change) < MOVER_MIN_CHANGE:
            continue
        moved.append(MarketMover(item=_ref(item), price=price, change_pct=change, profession=profession))
    risers = sorted((m for m in moved if m.change_pct > 0), key=lambda m: (-m.change_pct, m.item.name))
    fallers = sorted((m for m in moved if m.change_pct < 0), key=lambda m: (m.change_pct, m.item.name))
    return risers[:MOVERS], fallers[:MOVERS]


def is_stale(data_at: datetime, now: datetime) -> bool:
    """Whether data taken at ``data_at`` is too old to post at ``now``."""
    return now - data_at > timedelta(hours=MARKET_STALE_HOURS)


def build_report(
    kind: MarketReportKind,
    *,
    house_name: str,
    data_at: datetime,
    items: Mapping[int, ItemNumbers],
    recipes: Sequence[RecipeNumbers],
    now: datetime,
) -> MarketReport:
    """The whole report for one house's feed."""
    # The data's own day is still running: its typical price comes from a few hours of listings, so changes and
    # charts stop at the last whole day.
    end = data_at.astimezone(UTC).date() - timedelta(days=1)
    start = end if kind == "daily" else end - timedelta(days=6)
    risers, fallers = movers(items, recipes, kind, end)
    return MarketReport(
        kind=kind,
        house_name=house_name,
        data_at=data_at,
        stale=is_stale(data_at, now),
        period_start=start,
        period_end=end,
        gathering=gather_sections(items, kind, end),
        crafting=craft_sections(recipes, items, kind, end),
        risers=risers,
        fallers=fallers,
    )
