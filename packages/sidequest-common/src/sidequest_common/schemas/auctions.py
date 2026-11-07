"""Auction house prices: public prices, member price-watch alerts, and the bot's sync/alert feed.

``local://auctions-contract.md`` is the source of truth. Battle.net serves fifteen auction houses per ruleset (five
each for Alliance, Horde and Blackwater); SideQuest prices items from every house of its own faction. Money is
copper (an ``int``); the website and bot each format it as ``1g 20s 5c``.
"""

from datetime import date, datetime  # pydantic needs them at runtime
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, Field

AUCTION_TREND_DAYS = 14
AUCTION_HISTORY_DAYS = 90
MAX_AUCTION_WATCHES = 25
MAX_PRICE_IDS = 200
IMPORT_PRICES_LIMIT = 500
AUCTION_ALERT_COOLDOWN_HOURS = 24


class AuctionHousePrice(BaseModel):
    """One auction house's current price for an item."""

    house_id: int = Field(description="The auction house's Battle.net ID.")
    house_name: str = Field(description="The house's name, such as `Alliance Auction House`.")
    unit_price: int = Field(description="The lowest unit price listed at this house, in copper.")
    quantity: int = Field(description="Total quantity of priced listings at this house.")
    listings: int = Field(description="How many listings this house's price was built from.")
    updated_at: datetime = Field(description="When this house's price was last synced.")


class AuctionTrendPoint(BaseModel):
    """One day's lowest unit price in an item's price trend."""

    day: date
    unit_price: int = Field(description="The lowest unit price seen that day across the guild's faction houses.")


class ItemAuctionPrice(BaseModel):
    """``GET /api/auctions/prices/{item_id}``: one item's current price across every house of the guild's faction."""

    item_id: int = Field(description="The item's game ID.")
    unit_price: int | None = Field(
        description="The lowest unit price across every house, in copper. Null if nobody lists it."
    )
    quantity_total: int = Field(description="Total priced quantity across every house.")
    houses: list[AuctionHousePrice] = Field(description="Every house currently pricing this item.")
    trend: list[AuctionTrendPoint] = Field(description=f"The last {AUCTION_TREND_DAYS} days of daily low prices.")
    updated_at: datetime | None = Field(description="When the price was last synced. Null if nobody lists it.")


class ItemPriceSummary(BaseModel):
    """One item's price in a batch price lookup, without its per-house breakdown or trend."""

    item_id: int = Field(description="The item's game ID.")
    unit_price: int | None = Field(description="The lowest unit price across every house. Null if nobody lists it.")
    quantity_total: int = Field(description="Total priced quantity across every house.")
    updated_at: datetime | None = Field(description="When the price was last synced. Null if nobody lists it.")


class AuctionPriceMap(BaseModel):
    """``GET /api/auctions/prices?ids=...``: one entry per requested item ID, in request order."""

    prices: list[ItemPriceSummary]


class AuctionSyncHouse(BaseModel):
    """One house's counts from an auction sync."""

    house_id: int = Field(description="The auction house's Battle.net ID.")
    house_name: str = Field(description="The house's name, such as `Alliance Auction House`.")
    auctions: int = Field(description="Non-stackable auctions fetched from this house.")
    commodities: int = Field(description="Stackable commodity listings fetched from this house.")


class AuctionSyncReport(BaseModel):
    """``POST /api/guilds/{guild_id}/auctions/sync``: what the sync fetched, priced and queued."""

    houses: list[AuctionSyncHouse]
    items_priced: int = Field(description="Distinct items priced by this sync.")
    alerts_queued: int = Field(description="Price-watch alerts queued by this sync.")


class AuctionWatch(BaseModel):
    """One of a member's auction price watches."""

    id: UUID
    item_id: int = Field(description="The item's game ID.")
    item_name: str | None = Field(description="The item's name, if Battle.net knows it.")
    icon_url: str | None = Field(description="The item's icon, if Battle.net has one.")
    max_unit_price: int = Field(description="Alert when the item's lowest unit price is at or below this, in copper.")
    current_unit_price: int | None = Field(description="The item's current lowest unit price. Null if unpriced.")
    created_at: datetime
    last_alerted_at: datetime | None = Field(description="When this watch last queued an alert, if ever.")


class AuctionWatchCreate(BaseModel):
    """Body for ``POST /api/me/auction-watches`` (and the bot's member variant): upserts by ``item_id``."""

    item_id: int = Field(gt=0, description="The item's game ID.")
    max_unit_price: int = Field(
        ge=1, le=10_000_000_000, description="Alert when the item's lowest unit price is at or below this, in copper."
    )


class AuctionAlertSchema(BaseModel):
    """One queued price alert, as the bot's pending-alerts feed returns it."""

    id: UUID
    discord_user_id: int = Field(description="The watching member's Discord user ID, to DM.")
    member_name: str = Field(description="The watching member's display name at the time of the alert.")
    item_id: int = Field(description="The item's game ID.")
    item_name: str | None = Field(description="The item's name, if Battle.net knows it.")
    icon_url: str | None = Field(description="The item's icon, if Battle.net has one.")
    unit_price: int = Field(description="The price that triggered the alert, in copper.")
    max_unit_price: int = Field(description="The watch's threshold at the time of the alert, in copper.")
    quantity: int = Field(description="Total priced quantity at that price, across houses.")
    house_name: str = Field(description="The cheapest house's name.")
    created_at: datetime
