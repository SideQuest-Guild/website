"""Item schemas: game items from Battle.net, for item pages and item search."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

ITEM_SEARCH_PAGE_SIZE = 50
ITEM_SEARCH_MIN_LENGTH = 3


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
