"""The guild market report: what to gather and what to craft for gold, from one auction house's sale data.

The numbers come from a feed (``POST /api/market/feed``) that a price tracker sends for the guild's auction house:
each item's current price, what it really sold for and how many sell a day, plus the recipes that use them. The
site turns that feed into a daily and a weekly report, shown to guild members on the site and posted once a day by
the bot. The report only covers raw materials and crafted goods; it never names single listings or resale deals.
Money is copper (an ``int``).
"""

from datetime import date, datetime  # pydantic needs them at runtime
from typing import Literal

from pydantic import BaseModel, Field

MARKET_FEED_DAYS = 30
"""Days of daily prices the feed carries for each item."""
MARKET_STALE_HOURS = 36
"""A feed older than this is too old to post: the bot skips the day's report and the site says so."""
MARKET_AH_CUT = 0.05
"""The auction house's cut of a sale at a faction house."""

MarketReportKind = Literal["daily", "weekly"]


class MarketFeedDay(BaseModel):
    """One day of an item's prices in the feed."""

    day: date
    min_price: int = Field(ge=0, description="The day's lowest listed unit price, in copper. 0 if nobody listed it.")
    market: int = Field(ge=0, description="The day's typical unit price, in copper. 0 if unknown.")


class MarketFeedItem(BaseModel):
    """One item's current numbers in the feed."""

    item_id: int = Field(gt=0, description="The item's game ID.")
    name: str = Field(min_length=1, max_length=200, description="The item's name.")
    quality: str | None = Field(default=None, description="The item's quality, such as `COMMON` or `RARE`.")
    stack_size: int = Field(default=1, ge=1, description="How many fit in one stack.")
    vendor_buy: int = Field(default=0, ge=0, description="What a vendor sells it for, in copper. 0 if none does.")
    vendor_sell: int = Field(default=0, ge=0, description="What a vendor pays for it, in copper.")
    min_price: int = Field(ge=0, description="The lowest unit price listed now, in copper. 0 if nobody lists it.")
    quantity: int = Field(ge=0, description="How many are listed now.")
    market: int = Field(ge=0, description="The typical unit price over the last 14 days, in copper. 0 if unknown.")
    sale_price: int = Field(
        ge=0, description="The average unit price it actually sold for over the last 14 days, in copper. 0 if unknown."
    )
    sold_per_day: float = Field(ge=0, description="How many sold a day, on average, over the last 14 days.")
    days: list[MarketFeedDay] = Field(
        default_factory=list, description=f"Up to {MARKET_FEED_DAYS} days of daily prices, oldest first."
    )


class MarketFeedReagent(BaseModel):
    """One reagent of a recipe in the feed."""

    item_id: int = Field(gt=0, description="The reagent's game ID.")
    quantity: int = Field(gt=0, description="How many one craft uses.")


class MarketFeedRecipe(BaseModel):
    """One recipe in the feed: what it makes and what it uses."""

    recipe_id: int = Field(gt=0, description="The recipe's game ID.")
    name: str = Field(min_length=1, max_length=200, description="The recipe's name.")
    profession: str = Field(min_length=1, max_length=60, description="The profession, such as `Alchemy`.")
    crafted_item_id: int = Field(gt=0, description="The item it makes.")
    crafted_quantity: float = Field(default=1, gt=0, description="How many one craft makes, on average.")
    reagents: list[MarketFeedReagent] = Field(min_length=1, description="What one craft uses.")


class MarketFeed(BaseModel):
    """``POST /api/market/feed``: one auction house's numbers. Replaces the previous feed for that house."""

    house_id: int = Field(gt=0, description="The auction house's Battle.net ID.")
    house_name: str = Field(min_length=1, max_length=100, description="The house's name.")
    snapshot_at: datetime = Field(description="When the auction house data behind these numbers was taken.")
    items: list[MarketFeedItem] = Field(max_length=20_000, description="Every item the report may use.")
    recipes: list[MarketFeedRecipe] = Field(max_length=20_000, description="Every recipe the report may use.")


class MarketFeedReceipt(BaseModel):
    """What the site stored from a feed."""

    items: int = Field(description="Items stored.")
    recipes: int = Field(description="Recipes stored.")


class MarketItemRef(BaseModel):
    """An item named in the report."""

    item_id: int = Field(description="The item's game ID.")
    name: str = Field(description="The item's name.")
    quality: str | None = Field(default=None, description="The item's quality, such as `COMMON` or `RARE`.")


class MarketPoint(BaseModel):
    """One day of an item's price, for a small chart."""

    day: date
    price: int = Field(description="The day's typical unit price, in copper.")


class MarketZone(BaseModel):
    """A zone where a material can be gathered."""

    name: str = Field(description="The zone's name.")
    min_level: int = Field(description="The zone's lowest monster level.")
    max_level: int = Field(description="The zone's highest monster level.")


class MarketGatherPick(BaseModel):
    """A material worth gathering: what it sells for, how fast it sells, and where to get it."""

    item: MarketItemRef
    price: int = Field(description="What one sells for, in copper, before the auction house cut.")
    stack_size: int = Field(description="How many fit in one stack.")
    stack_price: int = Field(description="What a full stack sells for, in copper, before the cut.")
    sold_per_day: float = Field(description="How many sell a day.")
    change_pct: float | None = Field(
        description="Price change against the period before, in percent. Null without enough history."
    )
    skill: int = Field(description="The gathering skill needed. 0 if any character can get it.")
    min_level: int = Field(description="The lowest zone level where it can be gathered.")
    max_level: int = Field(description="The highest zone level where it can be gathered.")
    zones: list[MarketZone] = Field(description="Where to gather it, lowest level first.")
    trend: list[MarketPoint] = Field(description="Daily prices, oldest first.")


class MarketGatherSection(BaseModel):
    """The best materials for one gathering profession."""

    profession: str = Field(description="The profession, such as `Herbalism`, or `Cloth` for cloth from monsters.")
    picks: list[MarketGatherPick] = Field(description="Best first.")


class MarketReagentLine(BaseModel):
    """One reagent of a craft, with its cost."""

    item: MarketItemRef
    quantity: int = Field(description="How many one craft uses.")
    unit_price: int = Field(description="What one costs, in copper.")
    from_vendor: bool = Field(description="Whether a vendor sells it for less than the auction house.")


class MarketCraftPick(BaseModel):
    """A craft worth making: what it sells for, what its materials cost, and how fast it sells."""

    recipe_id: int = Field(description="The recipe's game ID.")
    recipe_name: str = Field(description="The recipe's name.")
    item: MarketItemRef
    makes: float = Field(description="How many one craft makes, on average.")
    price: int = Field(description="What one sells for, in copper, before the auction house cut.")
    mats_cost: int = Field(description="What the materials for one craft cost to buy, in copper.")
    profit: int = Field(description="Profit from one craft when you buy the materials, after the cut, in copper.")
    margin_pct: float = Field(description="Profit as a percent of the material cost.")
    sold_per_day: float = Field(description="How many sell a day.")
    change_pct: float | None = Field(
        description="Price change against the period before, in percent. Null without enough history."
    )
    cooldown_hours: float | None = Field(
        default=None, description="Hours before the recipe can be crafted again. Null if it has no cooldown."
    )
    reagents: list[MarketReagentLine] = Field(description="The materials for one craft.")
    trend: list[MarketPoint] = Field(description="Daily prices, oldest first.")


class MarketCraftSection(BaseModel):
    """The best crafts for one crafting profession."""

    profession: str = Field(description="The profession, such as `Alchemy`.")
    picks: list[MarketCraftPick] = Field(description="Best first.")


class MarketMover(BaseModel):
    """A material or craft whose price moved a lot."""

    item: MarketItemRef
    price: int = Field(description="What one sells for now, in copper.")
    change_pct: float = Field(description="Price change against the period before, in percent.")
    profession: str = Field(description="The profession that gathers or crafts it.")


class MarketReport(BaseModel):
    """``GET /api/market/report``: what to gather and craft for gold on the guild's auction house."""

    kind: MarketReportKind = Field(description="`daily` compares with the week before; `weekly` with last week.")
    house_name: str = Field(description="The auction house the numbers come from.")
    data_at: datetime = Field(description="When the auction house data was taken.")
    stale: bool = Field(description=f"Whether the data is more than {MARKET_STALE_HOURS} hours old.")
    period_start: date = Field(description="The first whole day the report covers.")
    period_end: date = Field(description="The last whole day the report covers: the day before `data_at`.")
    gathering: list[MarketGatherSection] = Field(description="One section per gathering profession.")
    crafting: list[MarketCraftSection] = Field(description="One section per crafting profession.")
    risers: list[MarketMover] = Field(description="Biggest price rises, largest first.")
    fallers: list[MarketMover] = Field(description="Biggest price drops, largest first.")
