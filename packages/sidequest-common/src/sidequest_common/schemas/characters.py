"""Characters from Battle.net: the guild roster, looked-up characters, their character sheets and the hero boards."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sidequest_common.schemas.events import WowClass

CHARACTER_SEARCH_MIN_LENGTH = 2
CHARACTER_SEARCH_LIMIT = 25
CHARACTER_SLUG_MAX_LENGTH = 50
CHARACTER_SLUG_PATTERN = r"^[^\s/?#-]+-[^\s/?#-]+$"
"""``name-surname``: two parts, and nothing that would leave a URL path segment."""
HERO_BOARD_SIZE = 10
MILESTONE_LEVELS = (40, 60)
RECENT_MILESTONES = 20


_CANONICAL_NAME_PARTS = 2


def canonical_character_name(character: str) -> str:
    """The addon's own identity (``SQ.CanonicalName``): ``First-Surname`` on Forever, ``Name-Realm`` elsewhere.

    Exports from before the addon's Forever identity fix (v0.8.0 and earlier) sent the raw space-joined
    ``First Surname`` shape, sometimes with a stray ``-<realm>`` tail the old, broken in-game normalizer
    appended (it treated the already-complete name as a bare name and appended the connected realm). Collapse
    every shape a stored or imported string might be in to the same two-part identity, so a character an old
    addon version created and one a fixed version sends later land on the same :class:`WowCharacter` row
    instead of creating a duplicate.
    """
    normalized = character.strip()
    if " " in normalized:
        normalized = normalized.replace(" ", "-", 1)
    parts = normalized.split("-")
    if len(parts) >= _CANONICAL_NAME_PARTS and parts[0] and parts[1]:
        return f"{parts[0]}-{parts[1]}"
    return normalized


def character_key(character: str) -> str:
    """The lookup key for :class:`WowCharacter.key`: :func:`canonical_character_name`, lowercased."""
    return canonical_character_name(character).lower()


class CharacterSummary(BaseModel):
    """A character's Battle.net summary.

    ``profile_found`` is false while Battle.net has no profile for the character (it publishes one some time after
    the character logs out); the summary then holds only what the guild roster says. ``rank_name`` is the guild
    rank's name as the addon last saw it, for roster members.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, serialize_by_alias=True)

    slug: str
    name: str
    surname: str
    level: int
    wow_class: WowClass | None = Field(alias="class")
    race: str | None
    faction: str | None
    guild_name: str | None
    guild_slug: str | None
    in_roster: bool
    guild_rank: int | None
    rank_name: str | None = None
    item_level: int | None
    spec: str | None
    achievement_points: int | None
    honorable_kills: int | None
    pvp_rank: int | None
    last_login_at: datetime | None
    profile_found: bool
    fetched_at: datetime | None


class CharacterGear(BaseModel):
    """One equipped item."""

    slot: str
    slot_name: str
    item_id: int
    name: str
    quality: str
    item_level: int | None
    enchantments: list[str]


class CharacterStatLine(BaseModel):
    """One line of the character pane, such as ``Strength`` and ``87``."""

    label: str
    value: str


class CharacterTalentTree(BaseModel):
    """Points spent in one talent tree of the active loadout."""

    name: str
    points: int


class CharacterProfessionSkill(BaseModel):
    """A profession and its skill."""

    name: str
    skill: int
    max_skill: int
    recipes: int


class CharacterReputationLine(BaseModel):
    """Standing with one faction. ``value`` is progress within the standing, out of ``max``."""

    faction: str
    standing: str
    value: int
    max: int


class CharacterAchievementLine(BaseModel):
    """An achievement earned recently."""

    name: str
    completed_at: datetime
    id: int | None = Field(None, description="The achievement's game ID, linking to its reference page.")


class CharacterSheet(BaseModel):
    """Everything the character page shows beyond the summary, as Battle.net published it at ``fetched_at``.

    A part Battle.net did not answer for is empty (or ``None`` for ``quests_completed``).
    """

    gear: list[CharacterGear]
    stats: list[CharacterStatLine]
    talents: list[CharacterTalentTree]
    professions: list[CharacterProfessionSkill]
    reputations: list[CharacterReputationLine]
    recent_achievements: list[CharacterAchievementLine]
    mounts: int
    pets: int
    toys: int
    quests_completed: int | None


class CharacterPage(CharacterSummary):
    """A character's summary and sheet. ``sheet`` is ``None`` while Battle.net has no profile for the character."""

    sheet: CharacterSheet | None


class RosterSyncReport(BaseModel):
    """What one roster sync changed. ``joined`` and ``left`` hold full names (``Name Surname``)."""

    members: int
    joined: list[str]
    left: list[str]
    profiles_refreshed: int
    characters_linked: int
    """Addon characters (``WowCharacter``) newly matched to their Battle.net character."""
    members_linked: int
    """Roster characters (``WowCharacter``) newly auto-linked to a member by proven Battle.net ownership."""


class RaidReadinessSettings(BaseModel):
    """The officers' raid readiness setting. ``min_item_level`` ``None`` marks nobody as under-geared."""

    min_item_level: int | None = Field(default=None, ge=1, le=1000)


class HeroBoardEntry(BaseModel):
    """One character on a Hall of Heroes board."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    slug: str
    name: str
    surname: str
    wow_class: WowClass | None = Field(alias="class")
    value: int


class HeroBoards(BaseModel):
    """The guild roster's top characters, ten to a board, from their Battle.net profiles."""

    item_level: list[HeroBoardEntry]
    honorable_kills: list[HeroBoardEntry]
    pvp_rank: list[HeroBoardEntry]
    achievement_points: list[HeroBoardEntry]


class CharacterMilestoneSchema(BaseModel):
    """A roster character reaching level 40 or 60. ``posted_at`` is ``None`` until the bot posts it to Discord."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, serialize_by_alias=True)

    id: UUID
    slug: str
    name: str
    surname: str
    wow_class: WowClass | None = Field(alias="class")
    level: int
    reached_at: datetime
    posted_at: datetime | None


class MilestonePosted(BaseModel):
    """Body for the bot's ``POST .../characters/milestones/{id}/posted``: the Discord message it posted."""

    discord_message_id: int | None = None
