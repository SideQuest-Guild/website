"""The guild directory (``addon/docs/directory.md`` in the addon repo is the contract).

Every member's addon keeps a record of their own character and shares it with the guild over addon messages:
professions and skill levels, character basics, craft cooldowns, attunements and key reputations, what they sell
and want to buy, and the crafting materials they hold. A record has five sections (``prof``, ``char``, ``cd``,
``market``, ``stock``); each travels and is stored on its own, as ``{v, at, d}`` (``relayed`` is addon-local and
never sent to the site). Newest ``at`` wins per character+section; ``d: null`` is a tombstone that deletes that
character's data for the section. An officer's sync carries the whole directory to the site in the ``SQX1:``
export's additive ``directory``/``item_names``/``recipe_names`` fields (``v`` stays 2; older sites ignore them).
"""

from datetime import datetime  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sidequest_common.schemas.guild_hub import GameClass

MAX_DIRECTORY_ENTRIES = 1000
"""One directory record per character; matches ``MAX_ROSTER_MEMBERS``."""
MAX_DIRECTORY_CHARACTER_LENGTH = 64
"""Mirrors ``epgp.MAX_NAME_LENGTH``; kept local here to avoid an import cycle with ``epgp.py``."""
MAX_DIRECTORY_PROFESSIONS = 10
"""Primary + secondary professions a character can have; generous headroom over the usual 2 + 3."""
MAX_DIRECTORY_RECIPES_PER_PROFESSION = 2000
MAX_DIRECTORY_ATTUNEMENTS = 50
MAX_DIRECTORY_REPUTATIONS = 30
MAX_DIRECTORY_COOLDOWNS = 50
MAX_MARKET_SELL = 100
MAX_MARKET_BUY = 100
MAX_MARKET_REQUESTS = 30
MARKET_REQUEST_NOTE_MAX = 80
MAX_STOCK_ENTRIES = 300
MAX_ITEM_NAMES = 4000
MAX_RECIPE_NAMES = 4000


def _empty_table_as_list(value: object) -> object:
    """Treat ``{}`` the same as ``[]``.

    The addon's Lua->JSON codec may emit ``{}`` for an empty table where a JSON array is meant (Lua can't tell
    an empty array from an empty object).
    """
    return [] if value == {} else value


# --- Addon export (``SQX1:``, additive): one character's directory record -----------------------------------------


class DirProfession(BaseModel):
    """One profession in a character's ``prof.professions`` list, primary or secondary."""

    name: str = Field(max_length=40)
    skill_line: int | None = None
    """The skill line id; ``None`` when the collector couldn't read it (e.g. the guild-roster fallback)."""
    skill: int
    max_skill: int
    recipes: list[int] | None = Field(default=None, max_length=MAX_DIRECTORY_RECIPES_PER_PROFESSION)
    """Learned recipe spell ids; ``None`` until the profession window has been opened once."""
    recipes_at: int | None = None

    _coerce_recipes = field_validator("recipes", mode="before")(_empty_table_as_list)


class DirProfData(BaseModel):
    """The ``prof`` section's ``d``: every profession the character has."""

    professions: list[DirProfession] = Field(default_factory=list, max_length=MAX_DIRECTORY_PROFESSIONS)

    _coerce_professions = field_validator("professions", mode="before")(_empty_table_as_list)


class DirReputation(BaseModel):
    """One tracked reputation, from ``SideQuest.Data.REPUTATIONS`` only."""

    faction_id: int
    standing: int
    value: int


class DirCharData(BaseModel):
    """The ``char`` section's ``d``: level, class, race, spec, item level, attunements, reputations."""

    level: int
    wow_class: GameClass = Field(alias="class")
    race: str = Field(max_length=20)
    spec: str | None = Field(default=None, max_length=30)
    item_level: float | None = None
    attunements: list[str] = Field(default_factory=list, max_length=MAX_DIRECTORY_ATTUNEMENTS)
    reputations: list[DirReputation] = Field(default_factory=list, max_length=MAX_DIRECTORY_REPUTATIONS)

    model_config = ConfigDict(populate_by_name=True)

    _coerce_lists = field_validator("attunements", "reputations", mode="before")(_empty_table_as_list)


class DirCooldown(BaseModel):
    """One craft cooldown; ``ready_at`` 0 means ready now."""

    key: str = Field(max_length=40)
    ready_at: int


class DirCdData(BaseModel):
    """The ``cd`` section's ``d``: craft cooldowns the character has."""

    cooldowns: list[DirCooldown] = Field(default_factory=list, max_length=MAX_DIRECTORY_COOLDOWNS)

    _coerce_cooldowns = field_validator("cooldowns", mode="before")(_empty_table_as_list)


class DirMarketSell(BaseModel):
    """One item the character sells. ``price`` in copper, ``None`` means "whisper me"."""

    item_id: int
    price: int | None = None
    qty: int
    crafted: bool = False


class DirMarketBuy(BaseModel):
    """A standing offer to buy a material. ``price`` in copper, ``None`` means "whisper me"."""

    item_id: int
    price: int | None = None


class DirMarketRequest(BaseModel):
    """One open request for materials someone else can fill."""

    id: str = Field(max_length=MAX_DIRECTORY_CHARACTER_LENGTH + 20)
    item_id: int
    qty: int
    price: int | None = None
    note: str | None = Field(default=None, max_length=MARKET_REQUEST_NOTE_MAX)
    at: int


class DirMarketData(BaseModel):
    """The ``market`` section's ``d``: what the character sells, buys and requests."""

    sell: list[DirMarketSell] = Field(default_factory=list, max_length=MAX_MARKET_SELL)
    buy: list[DirMarketBuy] = Field(default_factory=list, max_length=MAX_MARKET_BUY)
    requests: list[DirMarketRequest] = Field(default_factory=list, max_length=MAX_MARKET_REQUESTS)

    _coerce_lists = field_validator("sell", "buy", "requests", mode="before")(_empty_table_as_list)


class DirStockData(BaseModel):
    """The ``stock`` section's ``d``: crafting materials in bags and bank, as ``[item_id, count]`` pairs."""

    bags: list[tuple[int, int]] = Field(default_factory=list, max_length=MAX_STOCK_ENTRIES)
    bank: list[tuple[int, int]] = Field(default_factory=list, max_length=MAX_STOCK_ENTRIES)
    bank_at: int | None = None

    _coerce_lists = field_validator("bags", "bank", mode="before")(_empty_table_as_list)


class DirProfSection(BaseModel):
    """One stored ``prof`` section: ``{v, at, d}``. ``d: None`` is a tombstone."""

    v: str = Field(min_length=8, max_length=8)
    at: int
    d: DirProfData | None = None


class DirCharSection(BaseModel):
    """One stored ``char`` section: ``{v, at, d}``. ``d: None`` is a tombstone."""

    v: str = Field(min_length=8, max_length=8)
    at: int
    d: DirCharData | None = None


class DirCdSection(BaseModel):
    """One stored ``cd`` section: ``{v, at, d}``. ``d: None`` is a tombstone."""

    v: str = Field(min_length=8, max_length=8)
    at: int
    d: DirCdData | None = None


class DirMarketSection(BaseModel):
    """One stored ``market`` section: ``{v, at, d}``. ``d: None`` is a tombstone."""

    v: str = Field(min_length=8, max_length=8)
    at: int
    d: DirMarketData | None = None


class DirStockSection(BaseModel):
    """One stored ``stock`` section: ``{v, at, d}``. ``d: None`` is a tombstone."""

    v: str = Field(min_length=8, max_length=8)
    at: int
    d: DirStockData | None = None


class ExportDirectorySections(BaseModel):
    """The ``sections`` object of one ``directory[]`` entry.

    A section absent from the export leaves that part of the character's stored record untouched (the exporting
    client simply didn't hold anything newer). Unknown section keys, from a newer addon, are ignored.
    """

    prof: DirProfSection | None = None
    char: DirCharSection | None = None
    cd: DirCdSection | None = None
    market: DirMarketSection | None = None
    stock: DirStockSection | None = None

    model_config = ConfigDict(extra="ignore")


class ExportDirectoryEntry(BaseModel):
    """One character's directory record in the export payload's ``directory`` array."""

    character: str = Field(max_length=MAX_DIRECTORY_CHARACTER_LENGTH)
    sections: ExportDirectorySections


# --- Import counts (added to ``EpgpImportResult``) -----------------------------------------------------------------


class DirectorySectionImportCounts(BaseModel):
    """Rows applied for one directory section across an import, and rows skipped for having an older ``at``."""

    updated: int = 0
    skipped: int = 0


class DirectoryImportCounts(BaseModel):
    """Per-section counts for the ``directory`` array of one ``SQX1:`` import."""

    prof: DirectorySectionImportCounts = Field(default_factory=DirectorySectionImportCounts)
    char: DirectorySectionImportCounts = Field(default_factory=DirectorySectionImportCounts)
    cd: DirectorySectionImportCounts = Field(default_factory=DirectorySectionImportCounts)
    market: DirectorySectionImportCounts = Field(default_factory=DirectorySectionImportCounts)
    stock: DirectorySectionImportCounts = Field(default_factory=DirectorySectionImportCounts)


# --- ``/api/guild/*`` HTTP API schemas -------------------------------------------------------------------------


class GuildDirectoryProfession(BaseModel):
    """One profession on a ``GET /api/guild/directory`` character row."""

    name: str
    skill: int
    max_skill: int


class GuildDirectoryReputation(BaseModel):
    """One tracked reputation on a ``GET /api/guild/directory`` character row."""

    faction_id: int
    standing: int
    value: int


class GuildDirectoryCooldown(BaseModel):
    """One craft cooldown on a ``GET /api/guild/directory`` character row."""

    key: str
    ready_at: datetime


class GuildDirectoryFreshness(BaseModel):
    """When each section was last updated for a character; ``None`` means that section was never shared."""

    prof: datetime | None = None
    char: datetime | None = None
    cd: datetime | None = None
    market: datetime | None = None
    stock: datetime | None = None


class GuildDirectoryCharacter(BaseModel):
    """One character row of ``GET /api/guild/directory`` (member)."""

    character: str
    member_id: int | None
    member_name: str | None
    professions: list[GuildDirectoryProfession]
    level: int | None
    wow_class: GameClass | None = Field(default=None, alias="class")
    race: str | None
    spec: str | None
    item_level: float | None
    attunements: list[str]
    reputations: list[GuildDirectoryReputation]
    cooldowns: list[GuildDirectoryCooldown]
    freshness: GuildDirectoryFreshness

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class GuildDirectory(BaseModel):
    """Response for ``GET /api/guild/directory`` (member): every character with directory data."""

    characters: list[GuildDirectoryCharacter]


class GuildMarketSellRow(BaseModel):
    """One ``sell`` row of ``GET /api/guild/market`` (member)."""

    character: str
    member_name: str | None
    item_id: int
    item_name: str | None
    price: int | None
    qty: int
    crafted: bool


class GuildMarketBuyRow(BaseModel):
    """One ``buy`` row of ``GET /api/guild/market`` (member)."""

    character: str
    member_name: str | None
    item_id: int
    item_name: str | None
    price: int | None


class GuildMarketRequestRow(BaseModel):
    """One ``requests`` row of ``GET /api/guild/market`` (member)."""

    id: str
    character: str
    member_name: str | None
    item_id: int
    item_name: str | None
    qty: int
    price: int | None
    note: str | None
    at: datetime


class GuildMarket(BaseModel):
    """Response for ``GET /api/guild/market`` (member): everyone's sell/buy listings and open requests."""

    sell: list[GuildMarketSellRow]
    buy: list[GuildMarketBuyRow]
    requests: list[GuildMarketRequestRow]


class GuildStockRow(BaseModel):
    """One character's holdings on ``GET /api/guild/stock`` (member)."""

    character: str
    member_name: str | None
    bags: int
    bank: int
    bank_at: datetime | None


class GuildStock(BaseModel):
    """Response for ``GET /api/guild/stock?item_id=`` (member): who holds ``item_id``, in bags or bank."""

    item_id: int
    item_name: str | None
    rows: list[GuildStockRow]


__all__ = (
    "MARKET_REQUEST_NOTE_MAX",
    "MAX_DIRECTORY_ATTUNEMENTS",
    "MAX_DIRECTORY_CHARACTER_LENGTH",
    "MAX_DIRECTORY_COOLDOWNS",
    "MAX_DIRECTORY_ENTRIES",
    "MAX_DIRECTORY_PROFESSIONS",
    "MAX_DIRECTORY_RECIPES_PER_PROFESSION",
    "MAX_DIRECTORY_REPUTATIONS",
    "MAX_ITEM_NAMES",
    "MAX_MARKET_BUY",
    "MAX_MARKET_REQUESTS",
    "MAX_MARKET_SELL",
    "MAX_RECIPE_NAMES",
    "MAX_STOCK_ENTRIES",
    "DirCdData",
    "DirCdSection",
    "DirCharData",
    "DirCharSection",
    "DirCooldown",
    "DirMarketBuy",
    "DirMarketData",
    "DirMarketRequest",
    "DirMarketSection",
    "DirMarketSell",
    "DirProfData",
    "DirProfSection",
    "DirProfession",
    "DirReputation",
    "DirStockData",
    "DirStockSection",
    "DirectoryImportCounts",
    "DirectorySectionImportCounts",
    "ExportDirectoryEntry",
    "ExportDirectorySections",
    "GuildDirectory",
    "GuildDirectoryCharacter",
    "GuildDirectoryCooldown",
    "GuildDirectoryFreshness",
    "GuildDirectoryProfession",
    "GuildDirectoryReputation",
    "GuildMarket",
    "GuildMarketBuyRow",
    "GuildMarketRequestRow",
    "GuildMarketSellRow",
    "GuildStock",
    "GuildStockRow",
)
