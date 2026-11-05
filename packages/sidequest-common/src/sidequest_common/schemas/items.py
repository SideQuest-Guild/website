"""Item schemas: game items from Battle.net, for item pages and item search."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field

from sidequest_common.schemas.epgp import CHASE_MULTIPLIER, GP_BY_INVTYPE, LEGENDARY_GP, OS_PERCENT

ITEM_SEARCH_PAGE_SIZE = 50
ITEM_SEARCH_MIN_LENGTH = 3

# Battle.net's slot constants are the addon's ``INVTYPE_*`` names without the prefix, except this one.
_INVTYPE_BY_BATTLENET_SLOT = {"TWOHWEAPON": "INVTYPE_2HWEAPON"}


class ItemQuality(StrEnum):
    """An item quality, as Battle.net names it."""

    POOR = "POOR"
    COMMON = "COMMON"
    UNCOMMON = "UNCOMMON"
    RARE = "RARE"
    EPIC = "EPIC"
    LEGENDARY = "LEGENDARY"
    ARTIFACT = "ARTIFACT"
    HEIRLOOM = "HEIRLOOM"


class ItemLootPrice(BaseModel):
    """What SQL (the guild's loot rules) charges for an item, before an officer's choices.

    An officer can still change it at the table: a caster's one-hand weapon costs the two-hand price, and a tier
    token costs the price of the slot it's for.
    """

    main_spec: int = Field(description="GP for a main-spec win.")
    off_spec: int = Field(description=f"GP for an off-spec win: {OS_PERCENT}% of main spec, rounded half up.")
    chase: int = Field(description=f"GP when officers call it a chase item: main spec times {CHASE_MULTIPLIER}.")


def sql_price(inventory_type: str, quality: str) -> ItemLootPrice | None:
    """The SQL price of an item in this slot and quality, or ``None`` if the rules don't price its slot."""
    if quality == ItemQuality.LEGENDARY:
        main_spec = LEGENDARY_GP
        chase = LEGENDARY_GP  # legendary pieces are a flat price
    else:
        slot_gp = GP_BY_INVTYPE.get(_INVTYPE_BY_BATTLENET_SLOT.get(inventory_type, f"INVTYPE_{inventory_type}"))
        if slot_gp is None:
            return None
        main_spec = slot_gp
        chase = int(slot_gp * CHASE_MULTIPLIER + 0.5)
    return ItemLootPrice(main_spec=main_spec, off_spec=(main_spec * OS_PERCENT + 50) // 100, chase=chase)


class ItemSchema(BaseModel):
    """An item as returned by ``GET /api/items/{item_id}``, with the lines of its in-game tooltip."""

    model_config = ConfigDict(from_attributes=True)

    item_id: int = Field(description="The item's game ID.")
    name: str
    quality: str = Field(description="Battle.net's quality constant, such as `EPIC`.")
    quality_name: str = Field(description="The quality as the game shows it, such as `Epic`.")
    item_class: str = Field(description="The item class, such as `Weapon`.")
    item_subclass: str = Field(description="The item subclass, such as `Sword`.")
    inventory_type: str = Field(description="Battle.net's slot constant, such as `TWOHWEAPON`.")
    inventory_type_name: str = Field(description="The slot as the game shows it, such as `Two-Hand`.")
    item_level: int
    required_level: int
    sell_price: int = Field(description="What a vendor pays, in copper.")
    is_equippable: bool
    icon_url: str | None = Field(description="The item's icon on Blizzard's render server, if Battle.net has one.")
    tooltip: list[str] = Field(description="The tooltip's text lines in order, below the item's name.")

    @computed_field(description="What SQL charges for this item, or null if the loot rules don't price its slot.")
    @property
    def loot_price(self) -> ItemLootPrice | None:
        """The item's SQL price, from its slot and quality."""
        return sql_price(self.inventory_type, self.quality)


class ItemSearchResult(BaseModel):
    """One item in a search result. Search results carry no icon or tooltip; the item page has them."""

    item_id: int = Field(description="The item's game ID.")
    name: str
    quality: str = Field(description="Battle.net's quality constant, such as `EPIC`.")
    quality_name: str = Field(description="The quality as the game shows it, such as `Epic`.")
    inventory_type: str = Field(description="Battle.net's slot constant, such as `TWOHWEAPON`.")
    inventory_type_name: str = Field(description="The slot as the game shows it, such as `Two-Hand`.")
    item_level: int
    required_level: int


class ItemSearchPage(BaseModel):
    """One page of item search results, as returned by ``GET /api/items``. Battle.net stops at 1,000 results."""

    page: int = Field(description="This page's number, starting at 1.")
    page_count: int = Field(description="How many pages the search has.")
    results: list[ItemSearchResult]
