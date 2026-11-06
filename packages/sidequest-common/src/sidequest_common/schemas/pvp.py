"""Battleground scoreboards the addon records, and the members-only match history and PvP boards built from them.

The ``battlegrounds`` block is additive on top of the ``SQX1:`` export ``v: 2``: older sites ignore it, so the
version number doesn't change. The game hides the scoreboard while a match runs (``C_PvP.GetScoreInfo`` is secret
in an active match), so the addon records it once the match has ended.
"""

from datetime import datetime  # pydantic needs it at runtime
from enum import StrEnum
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field

from sidequest_common.schemas.events import WowClass

MAX_BATTLEGROUNDS = 50
"""Matches in one export."""
MAX_BATTLEGROUND_PLAYERS = 80
"""Scoreboard rows in one match (40 a side is the largest battleground)."""
SAME_MATCH_SECONDS = 120
"""Two recordings of the same battleground ending this close together are one match (several members record it)."""
PVP_MATCHES_PAGE_SIZE = 25
PVP_BOARD_SIZE = 10


class BattlegroundWinner(StrEnum):
    """Which side won a battleground."""

    ALLIANCE = "alliance"
    HORDE = "horde"
    DRAW = "draw"


class BattlegroundFaction(StrEnum):
    """A scoreboard row's side."""

    ALLIANCE = "alliance"
    HORDE = "horde"


class ExportBattlegroundPlayer(BaseModel):
    """One scoreboard row, as ``C_PvP.GetScoreInfo`` gives it once the match has ended.

    ``name`` is the player's name as the scoreboard shows it. ``wow_class`` is the class file name (``WARRIOR``),
    lowercased by the site. Counters the scoreboard doesn't show for this battleground are 0.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=64)
    faction: BattlegroundFaction
    race: str | None = Field(default=None, max_length=40)
    wow_class: str | None = Field(default=None, alias="class", max_length=20)
    killing_blows: int = Field(default=0, ge=0)
    honorable_kills: int = Field(default=0, ge=0)
    deaths: int = Field(default=0, ge=0)
    honor_gained: int = Field(default=0, ge=0)
    damage_done: int = Field(default=0, ge=0)
    healing_done: int = Field(default=0, ge=0)


class ExportBattleground(BaseModel):
    """One finished battleground in the export payload.

    ``id`` is the addon's own id for the recording (recorder plus end time); the site also merges recordings of the
    same match by other members (same ``instance_id``, ``ended_at`` within ``SAME_MATCH_SECONDS``).
    ``my_faction`` is the recorder's side. ``winner`` is ``None`` if the game didn't say.
    """

    id: str = Field(min_length=1, max_length=80)
    map: str = Field(min_length=1, max_length=80)
    instance_id: int = Field(ge=0)
    ended_at: int = Field(gt=0)
    duration: int = Field(default=0, ge=0)
    winner: BattlegroundWinner | None = None
    my_faction: BattlegroundFaction
    players: list[ExportBattlegroundPlayer] = Field(default_factory=list, max_length=MAX_BATTLEGROUND_PLAYERS)


class BattlegroundImportCounts(BaseModel):
    """Counts for the ``battlegrounds`` section of one import. ``merged`` matches another member already recorded."""

    new: int = 0
    merged: int = 0


class PvpPlayerRow(BaseModel):
    """One scoreboard row on the site. ``character_slug`` links a guild character's row to its character page."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    name: str
    faction: BattlegroundFaction
    race: str | None
    wow_class: WowClass | None = Field(alias="class")
    killing_blows: int
    honorable_kills: int
    deaths: int
    honor_gained: int
    damage_done: int
    healing_done: int
    guild_member: bool
    """True when the row is a SideQuest character."""
    character_slug: str | None


class PvpMatchSummary(BaseModel):
    """One battleground in the match history."""

    id: UUID
    map: str
    ended_at: datetime
    duration: int
    winner: BattlegroundWinner | None
    guild_faction: BattlegroundFaction
    """The side the recording member played on."""
    won: bool | None
    """Whether the guild's side won; ``None`` if the winner is unknown or a draw."""
    guild_players: list[str]
    """The SideQuest characters in the match."""
    recorded_by: str


class PvpMatchDetail(PvpMatchSummary):
    """One battleground with its full scoreboard, highest honorable kills first."""

    players: list[PvpPlayerRow]


class PvpMatchPage(BaseModel):
    """One page of the match history, newest first."""

    page: int
    page_count: int
    matches: list[PvpMatchSummary]


class PvpBoardEntry(BaseModel):
    """One guild character on a PvP board."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    name: str
    wow_class: WowClass | None = Field(alias="class")
    character_slug: str | None
    value: int


class PvpBoards(BaseModel):
    """Totals over every recorded battleground for SideQuest characters, ten to a board."""

    matches: int
    """Battlegrounds recorded in total."""
    wins: list[PvpBoardEntry]
    honorable_kills: list[PvpBoardEntry]
    killing_blows: list[PvpBoardEntry]
    honor_gained: list[PvpBoardEntry]
    damage_done: list[PvpBoardEntry]
    healing_done: list[PvpBoardEntry]
