"""The guild market report's stored feed: one auction house's item numbers and the recipes that use them.

A price tracker posts the whole feed for a house (``POST /api/market/feed``); the site replaces that house's
``MarketItem`` and ``MarketRecipe`` rows in one transaction and stamps ``MarketFeedState``. The report is computed
from these rows on request, so nothing here is per member.
"""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import BigInteger, Float, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class MarketFeedState(UUIDAuditBase):
    """When a house's feed last arrived, and when its auction house data was taken."""

    __tablename__ = "market_feed_state"
    __table_args__ = {"comment": "The market report feed: one row per auction house, stamped on every feed."}

    house_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    house_name: Mapped[str] = mapped_column(Text)
    snapshot_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    items: Mapped[int] = mapped_column(Integer, default=0)
    recipes: Mapped[int] = mapped_column(Integer, default=0)


class MarketItem(UUIDAuditBase):
    """One item's numbers at one house, from the latest feed. ``days`` holds ``[iso_day, min_price, market]``."""

    __tablename__ = "market_item"
    __table_args__ = (
        UniqueConstraint("house_id", "item_id", name="uq_market_item_house_item"),
        {"comment": "Market report feed: each item's prices and sales at one house; replaced on every feed."},
    )

    house_id: Mapped[int] = mapped_column(Integer, index=True)
    item_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    quality: Mapped[str | None] = mapped_column(Text, default=None)
    stack_size: Mapped[int] = mapped_column(Integer, default=1)
    vendor_buy: Mapped[int] = mapped_column(BigInteger, default=0)
    vendor_sell: Mapped[int] = mapped_column(BigInteger, default=0)
    min_price: Mapped[int] = mapped_column(BigInteger, default=0)
    quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    market: Mapped[int] = mapped_column(BigInteger, default=0)
    sale_price: Mapped[int] = mapped_column(BigInteger, default=0)
    sold_per_day: Mapped[float] = mapped_column(Float, default=0.0)
    days: Mapped[list] = mapped_column(JsonB, default=list)


class MarketRecipe(UUIDAuditBase):
    """One recipe from the latest feed. ``reagents`` holds ``[item_id, quantity]`` pairs."""

    __tablename__ = "market_recipe"
    __table_args__ = (
        UniqueConstraint("house_id", "recipe_id", name="uq_market_recipe_house_recipe"),
        {"comment": "Market report feed: recipes and their reagents; replaced on every feed."},
    )

    house_id: Mapped[int] = mapped_column(Integer, index=True)
    recipe_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    profession: Mapped[str] = mapped_column(Text)
    crafted_item_id: Mapped[int] = mapped_column(Integer)
    crafted_quantity: Mapped[float] = mapped_column(Float, default=1.0)
    reagents: Mapped[list] = mapped_column(JsonB, default=list)
