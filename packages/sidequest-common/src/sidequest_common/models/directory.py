"""The guild directory's per-character storage (``addon/docs/directory.md`` in the addon repo is the contract).

``CharacterDirectorySection`` tracks the last applied ``at`` per character+section (``prof``/``char``/``cd``/
``market``/``stock``) so newest-``at``-wins and tombstones (``d: null``) can be enforced uniformly; the ``prof``
section's data itself lands in the existing ``CharacterProfession``/``ProfessionRecipe``/``CharacterRecipeLink``
tables (replacing that character's professions wholesale), while ``char``/``cd``/``market``/``stock`` each get one
row per character here, deleted on a tombstone. ``ItemName`` is the shared item id -> name table fed by the
export's ``item_names``; names are kept, never cleared, when a later export omits one.
"""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime
from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class CharacterDirectorySection(UUIDAuditBase):
    """Freshness tracker: the last applied ``at`` for one character's directory section.

    Checked before writing any of the four tables below, and before replacing a character's professions from a
    ``prof`` section; an incoming ``at`` no newer than this is skipped.
    """

    __tablename__ = "character_directory_section"
    __table_args__ = (
        UniqueConstraint("character_id", "section", name="uq_character_directory_section_character_section"),
        {"comment": "Last applied `at` per character+directory section; newest `at` wins, enforced here."},
    )

    character_id: Mapped[UUID] = mapped_column(ForeignKey("wow_character.id", ondelete="CASCADE"), index=True)
    section: Mapped[str] = mapped_column(String(10))
    at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))


class CharacterDirectoryChar(UUIDAuditBase):
    """Latest ``char`` directory section per character: basics, attunements, and tracked reputations."""

    __tablename__ = "character_directory_char"
    __table_args__ = {"comment": "Latest `char` directory section per character: basics, attunements, reputations."}

    character_id: Mapped[UUID] = mapped_column(
        ForeignKey("wow_character.id", ondelete="CASCADE"), unique=True, index=True
    )
    level: Mapped[int] = mapped_column(Integer)
    wow_class: Mapped[str] = mapped_column(String(20))
    race: Mapped[str] = mapped_column(String(20))
    spec: Mapped[str | None] = mapped_column(String(30), default=None)
    item_level: Mapped[float | None] = mapped_column(Float, default=None)
    attunements: Mapped[list] = mapped_column(JsonB, default=list)
    reputations: Mapped[list] = mapped_column(JsonB, default=list)


class CharacterDirectoryCooldowns(UUIDAuditBase):
    """Latest ``cd`` directory section per character: craft cooldowns and when each is ready."""

    __tablename__ = "character_directory_cooldowns"
    __table_args__ = {"comment": "Latest `cd` directory section per character: craft cooldowns and ready times."}

    character_id: Mapped[UUID] = mapped_column(
        ForeignKey("wow_character.id", ondelete="CASCADE"), unique=True, index=True
    )
    cooldowns: Mapped[list] = mapped_column(JsonB, default=list)


class CharacterDirectoryMarket(UUIDAuditBase):
    """Latest ``market`` directory section per character: sell/buy listings and open material requests."""

    __tablename__ = "character_directory_market"
    __table_args__ = {"comment": "Latest `market` directory section per character: sell, buy, and requests."}

    character_id: Mapped[UUID] = mapped_column(
        ForeignKey("wow_character.id", ondelete="CASCADE"), unique=True, index=True
    )
    sell: Mapped[list] = mapped_column(JsonB, default=list)
    buy: Mapped[list] = mapped_column(JsonB, default=list)
    requests: Mapped[list] = mapped_column(JsonB, default=list)


class CharacterDirectoryStock(UUIDAuditBase):
    """Latest ``stock`` directory section per character: crafting materials held in bags and bank."""

    __tablename__ = "character_directory_stock"
    __table_args__ = {"comment": "Latest `stock` directory section per character: bag/bank material counts."}

    character_id: Mapped[UUID] = mapped_column(
        ForeignKey("wow_character.id", ondelete="CASCADE"), unique=True, index=True
    )
    bags: Mapped[list] = mapped_column(JsonB, default=list)
    bank: Mapped[list] = mapped_column(JsonB, default=list)
    bank_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)


class ItemName(UUIDAuditBase):
    """Item id -> display name, fed by the export's ``item_names``. Names are kept, never cleared."""

    __tablename__ = "item_name"
    __table_args__ = {"comment": "Item id -> display name, from the export's `item_names`; names are never cleared."}

    item_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(Text)
