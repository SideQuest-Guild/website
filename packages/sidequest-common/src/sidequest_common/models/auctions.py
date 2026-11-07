"""Auction house prices synced from Battle.net, member price watches, and the bot's alert queue.

``AuctionHousePriceRow`` holds each house's current price per item, replaced wholesale for a house on every sync.
``AuctionHouseState`` tracks which houses are currently part of the guild's faction, so a house dropped from the
faction (or gone empty) can have its stale price rows pruned. ``AuctionDailyHistory`` keeps one lowest-price row per
(item, day) for the trend chart, pruned past ``AUCTION_HISTORY_DAYS``. ``AuctionWatch``/``AuctionAlert`` back a
member's price alerts.
"""

from datetime import date, datetime  # SQLAlchemy resolves Mapped[] annotations at runtime
from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class AuctionHousePriceRow(UUIDAuditBase):
    """One auction house's current price for one item, keyed by ``(house_id, item_id)``.

    Replaced wholesale for a house on every sync: the sync deletes a house's existing rows and bulk-inserts the
    freshly aggregated ones in one transaction, so a price that drops off the house never lingers.
    """

    __tablename__ = "auction_house_price"
    __table_args__ = (
        UniqueConstraint("house_id", "item_id", name="uq_auction_house_price_house_item"),
        {"comment": "Each auction house's current lowest price per item; replaced wholesale on every sync."},
    )

    house_id: Mapped[int] = mapped_column(Integer, index=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    house_name: Mapped[str] = mapped_column(Text)
    unit_price: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(BigInteger)
    listings: Mapped[int] = mapped_column(Integer)


class AuctionHouseState(UUIDAuditBase):
    """Sync bookkeeping for one auction house: whether it's currently part of the guild's faction, and counts.

    ``is_active`` lets a sync prune ``AuctionHousePriceRow`` rows for a house that dropped out of the faction set
    (Battle.net could in principle reshuffle which houses are Alliance/Horde/Blackwater).
    """

    __tablename__ = "auction_house_state"
    __table_args__ = {"comment": "Per-house sync bookkeeping: whether it's part of the guild's faction, and counts."}

    house_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    house_name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    auctions_count: Mapped[int] = mapped_column(Integer, default=0)
    commodities_count: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)


class AuctionDailyHistory(UUIDAuditBase):
    """One item's lowest unit price and latest total quantity for one UTC day, across the faction's houses."""

    __tablename__ = "auction_daily_history"
    __table_args__ = (
        UniqueConstraint("item_id", "day", name="uq_auction_daily_history_item_day"),
        {"comment": "Daily lowest price and latest quantity per item, across the faction's houses."},
    )

    item_id: Mapped[int] = mapped_column(Integer, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    unit_price: Mapped[int] = mapped_column(BigInteger)
    quantity_total: Mapped[int] = mapped_column(BigInteger)


class AuctionWatch(UUIDAuditBase):
    """One member's price watch on an item: alert when the lowest unit price is at or below ``max_unit_price``."""

    __tablename__ = "auction_watch"
    __table_args__ = (
        UniqueConstraint("member_id", "item_id", name="uq_auction_watch_member_item"),
        {"comment": "A member's price-watch on an item. Deleted with the member."},
    )

    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("member.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    max_unit_price: Mapped[int] = mapped_column(BigInteger)
    last_alerted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    last_alerted_price: Mapped[int | None] = mapped_column(BigInteger, default=None)


class AuctionAlert(UUIDAuditBase):
    """One queued price alert for a watch, the bot DMs and acks (``posted_at``).

    ``discord_user_id``/``member_name`` are snapshotted at queue time so the alert reads correctly even if the
    member later renames or unlinks. ``created_at`` (from the audit base) orders the pending queue oldest first.
    """

    __tablename__ = "auction_alert"
    __table_args__ = {"comment": "Queued price-watch alerts for the bot to DM; posted_at is set once acked."}

    watch_id: Mapped[UUID] = mapped_column(ForeignKey("auction_watch.id", ondelete="CASCADE"), index=True)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    member_name: Mapped[str] = mapped_column(Text)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    unit_price: Mapped[int] = mapped_column(BigInteger)
    max_unit_price: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(BigInteger)
    house_name: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None, index=True)
