"""Game items as Battle.net describes them, and the items members wish for.

``BattlenetItem`` rows are filled on first read and fetched again when Battle.net starts serving a newer data version
(its static namespace, such as ``static-1.60.1_70399-forever-us``). ``ItemName`` (``directory.py``) is separate: the
names the addon reports, which exist even for items Battle.net does not know.
"""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class BattlenetItem(UUIDAuditBase):
    """One item from the Battle.net Item API, with the lines of its in-game tooltip."""

    __tablename__ = "battlenet_item"
    __table_args__ = {
        "comment": "Battle.net item data, filled on first read and refreshed when its data version changes."
    }

    item_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(Text)
    quality: Mapped[str] = mapped_column(String(20))
    quality_name: Mapped[str] = mapped_column(Text)
    item_class: Mapped[str] = mapped_column(Text)
    item_subclass: Mapped[str] = mapped_column(Text)
    inventory_type: Mapped[str] = mapped_column(String(30))
    inventory_type_name: Mapped[str] = mapped_column(Text)
    item_level: Mapped[int] = mapped_column(Integer)
    required_level: Mapped[int] = mapped_column(Integer)
    sell_price: Mapped[int] = mapped_column(Integer)
    is_equippable: Mapped[bool] = mapped_column(Boolean)
    icon_url: Mapped[str | None] = mapped_column(Text, default=None)
    tooltip: Mapped[list] = mapped_column(JsonB, default=list)
    data_version: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))


class ItemWish(UUIDAuditBase):
    """One item on a member's wishlist. Officers see who wants a drop; the loot rules don't change."""

    __tablename__ = "item_wish"
    __table_args__ = (
        UniqueConstraint("member_id", "item_id", name="uq_item_wish_member_item"),
        {"comment": "Items members want; officers see them next to loot points. Deleted with the member."},
    )

    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("member.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    note: Mapped[str | None] = mapped_column(Text, default=None)
