"""Characters from Battle.net: the SideQuest roster, characters looked up by exact name, and their character sheets.

A character is stored on its first lookup and fetched again on a read once its copy is older than ``REFRESH_AFTER``.
The bot's roster sync (``sync_roster``) keeps the roster rows current and refreshes the stalest profiles a few at a
time, so roster pages rarely wait on Battle.net. Battle.net publishes a profile only some time after its character
logs out: until then a roster member's row holds what the roster says, and a lookup of anyone else answers 404.
"""

import asyncio
import logging
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE
from sqlalchemy import delete, func, or_, select
from wow import NotFoundError, WowError

from sidequest_api.domain.characters.battlenet_recipes import translate_recipe
from sidequest_api.domain.recruitment.services import RecruitmentService
from sidequest_api.lib.roster import confirm_roster
from sidequest_common.models import (
    BattlenetCharacter,
    CharacterMilestone,
    CharacterProfession,
    CharacterRecipeLink,
    GuildConfig,
    GuildRosterSnapshot,
    Member,
    ProfessionRecipe,
    WowCharacter,
)
from sidequest_common.schemas import (
    CHARACTER_SEARCH_LIMIT,
    HERO_BOARD_SIZE,
    MILESTONE_LEVELS,
    RECENT_MILESTONES,
    CharacterAchievementLine,
    CharacterGear,
    CharacterHunterPet,
    CharacterPage,
    CharacterProfessionSkill,
    CharacterReputationLine,
    CharacterSheet,
    CharacterStatLine,
    CharacterSummary,
    CharacterTalentTree,
    HeroBoardEntry,
    HeroBoards,
    RosterSyncReport,
    SignupReadiness,
    WowClass,
    character_key,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Collection, Iterable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession
    from wow import AsyncClient
    from wow.models import (
        CharacterAchievements,
        CharacterEquipment,
        CharacterHunterPets,
        CharacterProfessions,
        CharacterReputations,
        CharacterSpecializations,
        CharacterStatistics,
        GuildMember,
    )

logger = logging.getLogger(__name__)

ROSTER_GUILD_SLUG = "sidequest"
REFRESH_AFTER = timedelta(hours=6)
SYNC_PROFILE_BATCH = 8
MISSING_CACHE_SECONDS = 600
RECENT_ACHIEVEMENTS = 10
BATTLENET_UNREACHABLE = "Battle.net did not answer; try again in a minute"

# Battle.net's playable class and race ids. The roster carries only ids; a profile carries names too.
CLASS_BY_ID = {
    1: WowClass.WARRIOR,
    2: WowClass.PALADIN,
    3: WowClass.HUNTER,
    4: WowClass.ROGUE,
    5: WowClass.PRIEST,
    7: WowClass.SHAMAN,
    8: WowClass.MAGE,
    9: WowClass.WARLOCK,
    11: WowClass.DRUID,
}
RACE_BY_ID = {1: "Human", 2: "Orc", 3: "Dwarf", 4: "Night Elf", 5: "Undead", 6: "Tauren", 7: "Gnome", 8: "Troll"}
FACTION_NAMES = {"ALLIANCE": "Alliance", "HORDE": "Horde"}
_CLASS_VALUES = {wow_class.value for wow_class in WowClass}

# Slugs Battle.net answered 404 for, with no stored row: asked again only after MISSING_CACHE_SECONDS.
_missing: dict[str, float] = {}
_MISSING_MAX = 1000


def full_name(name: str, surname: str) -> str:
    """``Name Surname``, as the game shows it."""
    return f"{name} {surname}"


def character_display_name(character: WowCharacter) -> str:
    """``First Surname``, or just the first name until the roster sync has matched a surname from Battle.net."""
    return full_name(character.name, character.surname) if character.surname else character.name


async def link_battlenet_characters(session: AsyncSession, member_id: int, character_ids: Collection[int]) -> int:
    """Link every still-unlinked :class:`WowCharacter` whose Battle.net id is in ``character_ids`` to ``member_id``.

    ``character_ids`` comes from the member's own Battle.net account profile (``wow.profile`` scope), so a match
    proves ownership; never overrides an existing claim/officer/signup/battlenet link. Call this both when a
    member (re)links Battle.net, with their freshly-fetched ids, and during roster sync, with every linked
    member's stored ids, so characters the addon only just reported still get linked. Returns how many it linked.
    """
    if not character_ids:
        return 0
    statement = select(WowCharacter).where(
        WowCharacter.member_id.is_(None), WowCharacter.blizzard_id.in_(character_ids)
    )
    linked = 0
    for character in (await session.execute(statement)).scalars():
        character.member_id = member_id
        character.source = "battlenet"
        linked += 1
    return linked


def _wow_class(name: str | None) -> str | None:
    value = (name or "").casefold().replace(" ", "")
    return value if value in _CLASS_VALUES else None


def _from_ms(timestamp: int) -> datetime | None:
    return datetime.fromtimestamp(timestamp / 1000, UTC) if timestamp > 0 else None


def _percent(value: float) -> str:
    return f"{value:.2f}%"


def talent_trees(specializations: CharacterSpecializations | None) -> list[CharacterTalentTree]:
    """Points per talent tree in the active loadout (the first one if none is marked active)."""
    groups = specializations.specialization_groups if specializations is not None else ()
    group = next((group for group in groups if group.is_active), groups[0] if groups else None)
    if group is None:
        return []
    return [
        CharacterTalentTree(name=tree.specialization_name, points=tree.spent_points) for tree in group.specializations
    ]


def spec_of(trees: list[CharacterTalentTree]) -> str | None:
    """The tree with the most points, which the game calls the character's spec. ``None`` before any points."""
    best = max(trees, key=lambda tree: tree.points, default=None)
    return best.name if best is not None and best.points > 0 else None


def _gear(equipment: CharacterEquipment | None) -> list[CharacterGear]:
    if equipment is None:
        return []
    return [
        CharacterGear(
            slot=item.slot.type,
            slot_name=item.slot.name,
            item_id=item.item.id,
            name=item.name,
            quality=item.quality.type,
            item_level=item.level.value if item.level is not None else None,
            enchantments=[enchantment.display_string for enchantment in item.enchantments],
        )
        for item in equipment.equipped_items
    ]


def _stats(stats: CharacterStatistics | None) -> list[CharacterStatLine]:
    if stats is None:
        return []
    pairs = [
        ("Health", f"{stats.health:,}"),
        (stats.power_type.name, f"{stats.power:,}"),
        ("Strength", f"{stats.strength.effective:,}"),
        ("Agility", f"{stats.agility.effective:,}"),
        ("Stamina", f"{stats.stamina.effective:,}"),
        ("Intellect", f"{stats.intellect.effective:,}"),
        ("Spirit", f"{stats.spirit.effective:,}"),
        ("Armor", f"{stats.armor.effective:,}"),
        ("Attack power", f"{stats.attack_power:,}"),
        ("Spell power", f"{stats.spell_power:,}"),
        ("Melee crit", _percent(stats.melee_crit.value)),
        ("Ranged crit", _percent(stats.ranged_crit.value)),
        ("Spell crit", _percent(stats.spell_crit.value)),
        ("Dodge", _percent(stats.dodge.value)),
        ("Parry", _percent(stats.parry.value)),
        ("Block", _percent(stats.block.value)),
    ]
    return [CharacterStatLine(label=label, value=value) for label, value in pairs]


def _professions(professions: CharacterProfessions | None) -> list[CharacterProfessionSkill]:
    if professions is None:
        return []
    skills = []
    for profession in (*professions.primaries, *professions.secondaries):
        best = max(profession.tiers, key=lambda tier: tier.max_skill_points, default=None)
        skills.append(
            CharacterProfessionSkill(
                name=profession.profession.name,
                skill=best.skill_points if best is not None else 0,
                max_skill=best.max_skill_points if best is not None else 0,
                recipes=sum(len(tier.known_recipes) for tier in profession.tiers),
            )
        )
    return skills


def _reputations(reputations: CharacterReputations | None) -> list[CharacterReputationLine]:
    if reputations is None:
        return []
    ordered = sorted(reputations.reputations, key=lambda reputation: -reputation.standing.raw)
    return [
        CharacterReputationLine(
            faction=reputation.faction.name,
            standing=reputation.standing.name,
            value=reputation.standing.value,
            max=reputation.standing.max,
            faction_id=reputation.faction.id,
            tier=reputation.standing.tier,
        )
        for reputation in ordered
    ]


def _recent_achievements(achievements: CharacterAchievements | None) -> list[CharacterAchievementLine]:
    """The latest earned achievements: Battle.net's recent events, or else the latest completed ones."""
    if achievements is None:
        return []
    earned = [(event.achievement.id, event.achievement.name, event.timestamp) for event in achievements.recent_events]
    if not earned:
        earned = [
            (entry.achievement.id, entry.achievement.name, entry.completed_timestamp)
            for entry in achievements.achievements
            if entry.completed_timestamp
        ]
    earned.sort(key=lambda row: -row[2])
    return [
        CharacterAchievementLine(id=id_, name=name, completed_at=datetime.fromtimestamp(timestamp / 1000, UTC))
        for id_, name, timestamp in earned[:RECENT_ACHIEVEMENTS]
    ]


def _hunter_pets(hunter_pets: CharacterHunterPets | None) -> list[CharacterHunterPet]:
    """A hunter's tamed pets, active first then by slot. Empty for non-hunters (Battle.net 404s the document)."""
    if hunter_pets is None:
        return []
    return [
        CharacterHunterPet(
            name=pet.name,
            level=pet.level,
            creature=pet.creature.name,
            creature_id=pet.creature.id,
            active=pet.is_active,
        )
        for pet in sorted(hunter_pets.hunter_pets, key=lambda pet: (not pet.is_active, pet.slot))
    ]


async def _optional[T](request: Awaitable[T]) -> T | None:
    """The document, or ``None`` if Battle.net has none (404). Any other Battle.net error propagates."""
    try:
        return await request
    except NotFoundError:
        return None


async def fetch_character(game_data: AsyncClient, slug: str) -> tuple[dict[str, object], CharacterProfessions | None]:
    """A character's column values and character sheet, built from all its profile documents.

    Also returns the raw professions document (for the roster sync's crafter-directory fill-in; ``None`` if
    Battle.net has none).

    Raises ``NotFoundError`` if Battle.net has no profile for ``slug``.
    """
    characters = game_data.characters
    profile = await characters.get(slug)
    try:
        async with asyncio.TaskGroup() as group:
            equipment = group.create_task(_optional(characters.equipment(slug)))
            statistics = group.create_task(_optional(characters.statistics(slug)))
            specializations = group.create_task(_optional(characters.specializations(slug)))
            professions = group.create_task(_optional(characters.professions(slug)))
            reputations = group.create_task(_optional(characters.reputations(slug)))
            pvp = group.create_task(_optional(characters.pvp_summary(slug)))
            achievements = group.create_task(_optional(characters.achievements(slug)))
            mounts = group.create_task(_optional(characters.mounts(slug)))
            pets = group.create_task(_optional(characters.pets(slug)))
            toys = group.create_task(_optional(characters.toys(slug)))
            completed = group.create_task(_optional(characters.completed_quests(slug)))
            pet_stable = group.create_task(_optional(characters.hunter_pets(slug)))
    except* WowError as failures:
        # Callers catch the WowError itself, not the ExceptionGroup a TaskGroup wraps it in.
        raise failures.exceptions[0] from None
    trees = talent_trees(specializations.result())
    mounts_doc, pets_doc, toys_doc, completed_doc = mounts.result(), pets.result(), toys.result(), completed.result()
    sheet = CharacterSheet(
        gear=_gear(equipment.result()),
        stats=_stats(statistics.result()),
        talents=trees,
        professions=_professions(professions.result()),
        reputations=_reputations(reputations.result()),
        recent_achievements=_recent_achievements(achievements.result()),
        hunter_pets=_hunter_pets(pet_stable.result()),
        mounts=len(mounts_doc.mounts) if mounts_doc is not None else 0,
        pets=len(pets_doc.pets) if pets_doc is not None else 0,
        toys=len(toys_doc.toys) if toys_doc is not None else 0,
        quests_completed=len(completed_doc.quests) if completed_doc is not None else None,
    )
    pvp_doc = pvp.result()
    values: dict[str, object] = {
        "slug": slug,
        "blizzard_id": profile.id,
        "name": profile.name,
        "surname": profile.surname,
        "level": profile.level,
        "wow_class": _wow_class(profile.character_class.name),
        "race": profile.race.name,
        "faction": profile.faction.name,
        "guild_name": profile.guild.name if profile.guild is not None else None,
        "guild_slug": profile.guild.slug if profile.guild is not None else None,
        "profile_found": True,
        "item_level": profile.equipped_item_level or None,
        "achievement_points": profile.achievement_points,
        "honorable_kills": pvp_doc.honorable_kills if pvp_doc is not None else None,
        "pvp_rank": pvp_doc.pvp_rank if pvp_doc is not None else None,
        "spec": spec_of(trees),
        "last_login_at": _from_ms(profile.last_login_timestamp),
        "sheet": sheet.model_dump(mode="json"),
        "fetched_at": datetime.now(UTC),
    }
    return values, professions.result()


async def upsert_character_profession(
    session: AsyncSession,
    character_id: UUID,
    profession: str,
    *,
    skill: int,
    max_skill: int,
    scanned_at: datetime,
    recipes: Iterable[tuple[int, str, int | None]],
) -> None:
    """Upsert one character's profession skill and wholesale-replace its known recipes.

    Shared by the addon's ``SQX1:`` import (:meth:`EpgpService._import_professions`) and the Battle.net roster
    sync (:meth:`CharactersService._sync_crafter_professions`). ``recipes`` is ``(recipe_id, name, item_id)`` in
    the game's own recipe-id space (the addon contract's ``recipes[].id`` and Battle.net's skill-tier endpoint
    share this space; only Battle.net's character-professions endpoint answers in a different one). A recipe
    already known under this id keeps its stored ``item_id`` when the new data has none, never downgrading a
    known item to unknown.
    """
    row = (
        await session.execute(
            select(CharacterProfession).where(
                CharacterProfession.character_id == character_id, CharacterProfession.profession == profession
            )
        )
    ).scalar_one_or_none()
    is_new = row is None
    row = row or CharacterProfession(character_id=character_id, profession=profession)
    row.skill = skill
    row.max_skill = max_skill
    row.scanned_at = scanned_at
    if is_new:
        session.add(row)
    await session.flush()
    await session.execute(delete(CharacterRecipeLink).where(CharacterRecipeLink.profession_id == row.id))
    for recipe_id, name, item_id in recipes:
        recipe_row = (
            await session.execute(select(ProfessionRecipe).where(ProfessionRecipe.recipe_id == recipe_id))
        ).scalar_one_or_none()
        if recipe_row is None:
            recipe_row = ProfessionRecipe(recipe_id=recipe_id, name=name, item_id=item_id)
            session.add(recipe_row)
            await session.flush()
        else:
            recipe_row.name = name
            if item_id is not None:
                recipe_row.item_id = item_id
        session.add(CharacterRecipeLink(profession_id=row.id, recipe_id=recipe_row.id))
    await session.flush()


def to_summary(character: BattlenetCharacter, rank_names: dict[int, str] | None = None) -> CharacterSummary:
    """The API summary of a stored character, with its guild rank's name when the addon has seen it."""
    summary = CharacterSummary.model_validate(character)
    if character.guild_rank is not None and rank_names:
        summary.rank_name = rank_names.get(character.guild_rank)
    return summary


def to_page(character: BattlenetCharacter, rank_names: dict[int, str] | None = None) -> CharacterPage:
    """The full character page of a stored character."""
    summary = to_summary(character, rank_names)
    sheet = CharacterSheet.model_validate(character.sheet) if character.sheet is not None else None
    return CharacterPage.model_validate({**summary.model_dump(), "sheet": sheet})


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class BattlenetCharactersRepository(SQLAlchemyAsyncRepository[BattlenetCharacter]):
    """Battle.net character persistence."""

    model_type = BattlenetCharacter


class CharactersService(SQLAlchemyAsyncRepositoryService[BattlenetCharacter]):
    """Character lookup, roster search, the roster sync and the hero boards."""

    repository_type = BattlenetCharactersRepository

    async def rank_names(self) -> dict[int, str]:
        """Guild rank names by rank index, as the addon's roster export last reported them."""
        statement = select(GuildRosterSnapshot.rank_index, GuildRosterSnapshot.rank).where(
            GuildRosterSnapshot.rank != ""
        )
        return dict((await self.repository.session.execute(statement)).tuples().all())

    async def get_character(self, slug: str, game_data: AsyncClient) -> BattlenetCharacter:
        """The character, fetched from Battle.net if never stored or older than ``REFRESH_AFTER``.

        A stored character is served as it is when Battle.net fails or no longer has its profile. 404 if Battle.net
        has no such character and it was never stored.
        """
        stored = await self.get_one_or_none(slug=slug)
        now = datetime.now(UTC)
        if stored is not None and stored.fetched_at is not None and now - stored.fetched_at < REFRESH_AFTER:
            return stored
        missing_since = _missing.get(slug)
        if stored is None and missing_since is not None and time.monotonic() - missing_since < MISSING_CACHE_SECONDS:
            raise NotFoundException(self._missing_message(slug))
        try:
            return await self._refresh(slug, stored, game_data)
        except NotFoundError as exc:
            if stored is not None:
                stored.fetched_at = now
                return await self.update(stored, auto_commit=True)
            if len(_missing) >= _MISSING_MAX:
                _missing.pop(next(iter(_missing)))
            _missing[slug] = time.monotonic()
            raise NotFoundException(self._missing_message(slug)) from exc
        except WowError as exc:
            if stored is not None:
                return stored
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc

    @staticmethod
    def _missing_message(slug: str) -> str:
        return (
            f"Battle.net has no character {slug}. It publishes a character some time after it logs out, so check "
            "the name and surname, or try again later."
        )

    async def _refresh(
        self, slug: str, stored: BattlenetCharacter | None, game_data: AsyncClient
    ) -> BattlenetCharacter:
        """Fetch the character and store it. Raises ``NotFoundError``/``WowError`` from Battle.net."""
        values, professions = await fetch_character(game_data, slug)
        if stored is None:
            try:
                row = await self.create(BattlenetCharacter(**values), auto_commit=True)
            except IntegrityError:
                # Another request stored the same character first; theirs is as fresh as ours.
                await self.repository.session.rollback()
                return await self.get_one(slug=slug)
        else:
            previous_level = stored.level
            for field, value in values.items():
                setattr(stored, field, value)
            if stored.in_roster:
                await self._note_milestone(stored, previous_level)
            row = await self.update(stored, auto_commit=True)
        await self._sync_crafter_professions(row, professions, row.last_login_at)
        await self.repository.session.commit()
        return row

    async def _note_milestone(self, row: BattlenetCharacter, previous_level: int) -> None:
        """Queue a milestone if the character just passed level 40 or 60 (the higher one, if both)."""
        reached = [level for level in MILESTONE_LEVELS if previous_level < level <= row.level]
        if not reached:
            return
        session = self.repository.session
        level = max(reached)
        statement = select(CharacterMilestone.id).where(
            CharacterMilestone.slug == row.slug, CharacterMilestone.level == level
        )
        if await session.scalar(statement) is None:
            session.add(
                CharacterMilestone(
                    slug=row.slug,
                    name=row.name,
                    surname=row.surname,
                    wow_class=row.wow_class,
                    level=level,
                    reached_at=datetime.now(UTC),
                )
            )

    async def _sync_crafter_professions(
        self, character: BattlenetCharacter, professions: CharacterProfessions | None, as_of: datetime | None
    ) -> None:
        """Fill the crafter directory from Battle.net, for a roster member the addon has never scanned.

        Writes one profession at a time, each only when there's no stored row for this character/profession yet,
        or the stored row's ``scanned_at`` is older than ``as_of`` (the character's last logout, Battle.net's own
        freshness bound for this document): an addon scan newer than Battle.net's data is never overwritten.
        Known recipes with no entry in :func:`translate_recipe`'s map are skipped, never invented. No-ops without
        a professions document (character under level 10, or Battle.net hasn't published one since last logout)
        or without ``as_of`` (no logout recorded yet).
        """
        if professions is None or as_of is None:
            return
        session = self.repository.session
        wow_character = await self._get_or_create_crafter_character(character)
        for profession in (*professions.primaries, *professions.secondaries):
            best = max(profession.tiers, key=lambda tier: tier.max_skill_points, default=None)
            if best is None:
                continue
            existing_scanned_at = (
                await session.execute(
                    select(CharacterProfession.scanned_at).where(
                        CharacterProfession.character_id == wow_character.id,
                        CharacterProfession.profession == profession.profession.name,
                    )
                )
            ).scalar_one_or_none()
            if existing_scanned_at is not None and existing_scanned_at >= as_of:
                continue
            recipes = [
                (translated.recipe_id, recipe.name, translated.item_id)
                for recipe in best.known_recipes
                if (translated := translate_recipe(recipe.id)) is not None
            ]
            await upsert_character_profession(
                session,
                wow_character.id,
                profession.profession.name,
                skill=best.skill_points,
                max_skill=best.max_skill_points,
                scanned_at=as_of,
                recipes=recipes,
            )

    async def _get_or_create_crafter_character(self, character: BattlenetCharacter) -> WowCharacter:
        """The ``WowCharacter`` row to hang ``character``'s professions on.

        Matched first by ``blizzard_id``, then by the addon's own key (``character_key`` of ``Name-Surname``), so
        a character the addon has never scanned gets one new row keyed exactly as the addon would key it: a later
        addon import for the same character lands on this row instead of creating a duplicate.
        """
        session = self.repository.session
        if character.blizzard_id is not None:
            existing = (
                await session.execute(select(WowCharacter).where(WowCharacter.blizzard_id == character.blizzard_id))
            ).scalar_one_or_none()
            if existing is not None:
                return existing
        key = character_key(full_name(character.name, character.surname))
        existing = (await session.execute(select(WowCharacter).where(WowCharacter.key == key))).scalar_one_or_none()
        if existing is not None:
            existing.blizzard_id = existing.blizzard_id or character.blizzard_id
            existing.slug = existing.slug or character.slug
            existing.surname = existing.surname or character.surname
            return existing
        row = WowCharacter(
            name=character.name,
            realm="",
            key=key,
            source="import",
            blizzard_id=character.blizzard_id,
            surname=character.surname,
            slug=character.slug,
        )
        session.add(row)
        await session.flush()
        return row

    async def pending_milestones(self) -> list[CharacterMilestone]:
        """Milestones the bot has not posted yet, oldest first."""
        statement = (
            select(CharacterMilestone)
            .where(CharacterMilestone.posted_at.is_(None))
            .order_by(CharacterMilestone.reached_at)
        )
        return list((await self.repository.session.execute(statement)).scalars())

    async def recent_milestones(self) -> list[CharacterMilestone]:
        """The latest milestones, newest first, posted or not."""
        statement = select(CharacterMilestone).order_by(CharacterMilestone.reached_at.desc()).limit(RECENT_MILESTONES)
        return list((await self.repository.session.execute(statement)).scalars())

    async def mark_milestone_posted(self, milestone_id: UUID, discord_message_id: int | None) -> None:
        """Record that the bot posted a milestone. 404 if there's no such milestone."""
        session = self.repository.session
        milestone = await session.get(CharacterMilestone, milestone_id)
        if milestone is None:
            msg = f"No milestone {milestone_id}"
            raise NotFoundException(msg)
        milestone.posted_at = datetime.now(UTC)
        milestone.discord_message_id = discord_message_id
        await session.commit()

    async def search(self, query: str | None) -> list[BattlenetCharacter]:
        """Stored characters whose ``Name Surname`` contains ``query``, roster first; the roster if no query."""
        model = BattlenetCharacter
        if query is None:
            statement = select(model).where(model.in_roster.is_(True)).order_by(model.guild_rank, model.name)
        else:
            pattern = f"%{_escape_like(query.casefold())}%"
            full = func.lower(model.name + " " + model.surname)
            statement = (
                select(model)
                .where(or_(full.like(pattern, escape="\\"), model.slug.like(pattern, escape="\\")))
                .order_by(model.in_roster.desc(), model.level.desc(), model.name)
                .limit(CHARACTER_SEARCH_LIMIT)
            )
        return list((await self.repository.session.execute(statement)).scalars())

    async def sync_roster(self, game_data: AsyncClient) -> RosterSyncReport:
        """Bring the stored roster up to Battle.net's guild roster, link addon characters, refresh stale profiles."""
        try:
            roster = await game_data.guilds.roster(ROSTER_GUILD_SLUG)
        except WowError as exc:
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
        session = self.repository.session
        model = BattlenetCharacter
        now = datetime.now(UTC)
        slugs = [member.character.slug for member in roster.members]
        stored = {
            row.slug: row
            for row in (
                await session.execute(select(model).where(or_(model.in_roster.is_(True), model.slug.in_(slugs))))
            ).scalars()
        }
        first_sync = not any(row.in_roster for row in stored.values())
        joined: list[str] = []
        for member in roster.members:
            row = stored.get(member.character.slug)
            was_in_roster = row is not None and row.in_roster
            if row is None:
                row = self._roster_row(member)
                session.add(row)
            else:
                previous_level = row.level
                self._apply_roster(row, member)
                if was_in_roster:
                    await self._note_milestone(row, previous_level)
            if not was_in_roster and not first_sync:
                joined.append(full_name(row.name, row.surname))
                row.joined_roster_at = now
            row.in_roster = True
            row.left_roster_at = None
            row.guild_rank = member.rank
            row.guild_name = roster.guild.name
            row.guild_slug = roster.guild.slug
        left = []
        for slug, row in stored.items():
            if row.in_roster and slug not in slugs:
                row.in_roster = False
                row.left_roster_at = now
                row.guild_rank = None
                left.append(full_name(row.name, row.surname))
        await session.flush()
        linked = await self._link_addon_characters(roster.members)
        members_linked = await self._link_battlenet_owned_characters()
        members_confirmed = await self._confirm_battlenet_owned_members()
        await session.commit()
        try:
            await RecruitmentService(session).evaluate(now)
        except Exception:
            logger.exception("Recruitment drive evaluation failed after roster sync; roster sync result is unaffected")
        refreshed = await self._refresh_stalest(game_data, now)
        return RosterSyncReport(
            members=len(roster.members),
            joined=joined,
            left=left,
            profiles_refreshed=refreshed,
            characters_linked=linked,
            members_linked=members_linked,
            members_confirmed=members_confirmed,
        )

    @staticmethod
    def _roster_row(member: GuildMember) -> BattlenetCharacter:
        character = member.character
        return BattlenetCharacter(
            slug=character.slug,
            blizzard_id=character.id,
            name=character.name,
            surname=character.surname,
            level=character.level,
            wow_class=CLASS_BY_ID.get(character.playable_class.id),
            race=RACE_BY_ID.get(character.playable_race.id),
            faction=FACTION_NAMES.get(character.faction.type),
            in_roster=False,
        )

    @staticmethod
    def _apply_roster(row: BattlenetCharacter, member: GuildMember) -> None:
        """Roster facts that may be newer than the stored profile: ids, names and a higher level."""
        character = member.character
        row.blizzard_id = character.id
        row.name = character.name
        row.surname = character.surname
        row.level = max(row.level, character.level)
        row.wow_class = row.wow_class or CLASS_BY_ID.get(character.playable_class.id)
        row.race = row.race or RACE_BY_ID.get(character.playable_race.id)
        row.faction = row.faction or FACTION_NAMES.get(character.faction.type)

    async def _link_addon_characters(self, members: tuple[GuildMember, ...]) -> int:
        """Match unlinked addon characters to roster members by name, where exactly one roster member has it."""
        counts = Counter(member.character.name.casefold() for member in members)
        by_name = {
            member.character.name.casefold(): member.character
            for member in members
            if counts[member.character.name.casefold()] == 1
        }
        if not by_name:
            return 0
        statement = select(WowCharacter).where(
            WowCharacter.blizzard_id.is_(None), func.lower(WowCharacter.name).in_(list(by_name))
        )
        linked = 0
        for addon_character in (await self.repository.session.execute(statement)).scalars():
            character = by_name[addon_character.name.casefold()]
            addon_character.blizzard_id = character.id
            addon_character.surname = character.surname
            addon_character.slug = character.slug
            linked += 1
        return linked

    async def _link_battlenet_owned_characters(self) -> int:
        """Link roster characters to a member when that member's linked Battle.net account owns them.

        Every linked member's stored ``battlenet_character_ids`` is checked against every still-unlinked
        character's ``blizzard_id`` (filled above by :meth:`_link_addon_characters`), so this also catches
        characters the addon only just reported for a member who linked Battle.net earlier.
        """
        statement = select(Member.id, Member.battlenet_character_ids).where(Member.battlenet_character_ids.is_not(None))
        linked = 0
        for member_id, character_ids in (await self.repository.session.execute(statement)).all():
            linked += await link_battlenet_characters(self.repository.session, member_id, character_ids)
        return linked

    async def _confirm_battlenet_owned_members(self) -> int:
        """Auto-confirm an unconfirmed member whose linked Battle.net account owns an in-game roster character.

        Runs after :meth:`_link_battlenet_owned_characters`, so a character the addon only just reported this
        sync still counts. Never touches a member already confirmed, nor one an officer removed
        (``roster_removed_at`` set): they stay unconfirmed until an officer confirms them again.
        """
        session = self.repository.session
        roster_ids_statement = select(BattlenetCharacter.blizzard_id).where(BattlenetCharacter.in_roster.is_(True))
        roster_ids = {row for row in (await session.execute(roster_ids_statement)).scalars() if row is not None}
        if not roster_ids:
            return 0
        statement = select(Member).where(
            Member.roster_confirmed_at.is_(None),
            Member.roster_removed_at.is_(None),
            Member.battlenet_character_ids.is_not(None),
        )
        confirmed = 0
        for member in (await session.execute(statement)).scalars():
            if roster_ids.intersection(member.battlenet_character_ids or ()):
                confirm_roster(member, via="battlenet")
                confirmed += 1
        return confirmed

    async def _refresh_stalest(self, game_data: AsyncClient, now: datetime) -> int:
        """Refresh up to ``SYNC_PROFILE_BATCH`` stale profiles, roster first. Stops early if Battle.net fails.

        Stays sequential: every ``_refresh`` call reads and writes through ``self.repository.session``, one
        request-scoped ``AsyncSession`` shared by the whole service. SQLAlchemy's ``AsyncSession`` isn't safe for
        concurrent use from multiple tasks (overlapping ``execute``/``commit``/``rollback`` calls on one session
        corrupt its transaction state), so fanning these out with a semaphore or ``TaskGroup`` would race on that
        one session rather than actually run the Battle.net fetches in parallel. Giving each task its own session
        would need a sessionmaker threaded into this service, a bigger change than this batch touches.
        """
        model = BattlenetCharacter
        statement = (
            select(model)
            .where(or_(model.fetched_at.is_(None), model.fetched_at < now - REFRESH_AFTER))
            .order_by(model.in_roster.desc(), model.fetched_at.asc().nulls_first())
            .limit(SYNC_PROFILE_BATCH)
        )
        refreshed = 0
        for row in list((await self.repository.session.execute(statement)).scalars()):
            try:
                await self._refresh(row.slug, row, game_data)
            except NotFoundError:
                row.fetched_at = now
                await self.update(row, auto_commit=True)
            except WowError:
                break
            else:
                refreshed += 1
        return refreshed

    async def hero_boards(self) -> HeroBoards:
        """The roster's top ten by item level, honorable kills, PvP rank, achievement points, and collections.

        Collections (mounts/pets/toys) counts come from the stored character sheet, no new Battle.net calls.
        """
        statement = select(BattlenetCharacter).where(BattlenetCharacter.in_roster.is_(True))
        roster = list((await self.repository.session.execute(statement)).scalars())

        def board(field: str) -> list[HeroBoardEntry]:
            ranked = sorted(
                (row for row in roster if (getattr(row, field) or 0) > 0),
                key=lambda row: (-getattr(row, field), row.name),
            )
            return [
                HeroBoardEntry(
                    slug=row.slug,
                    name=row.name,
                    surname=row.surname,
                    wow_class=row.wow_class,
                    value=getattr(row, field),
                )
                for row in ranked[:HERO_BOARD_SIZE]
            ]

        def sheet_board(key: str) -> list[HeroBoardEntry]:
            counts = [(row, (row.sheet or {}).get(key) or 0) for row in roster]
            ranked = sorted((pair for pair in counts if pair[1] > 0), key=lambda pair: (-pair[1], pair[0].name))
            return [
                HeroBoardEntry(slug=row.slug, name=row.name, surname=row.surname, wow_class=row.wow_class, value=value)
                for row, value in ranked[:HERO_BOARD_SIZE]
            ]

        return HeroBoards(
            item_level=board("item_level"),
            honorable_kills=board("honorable_kills"),
            pvp_rank=board("pvp_rank"),
            achievement_points=board("achievement_points"),
            mounts=sheet_board("mounts"),
            pets=sheet_board("pets"),
            toys=sheet_board("toys"),
        )


async def raid_min_item_level(session: AsyncSession, guild_id: int) -> int | None:
    """The officers' minimum equipped item level for raids, or ``None`` if they set none."""
    statement = select(GuildConfig.raid_min_item_level).where(GuildConfig.guild_id == guild_id)
    return (await session.execute(statement)).scalar_one_or_none()


async def signup_readiness(
    session: AsyncSession, characters: list[str | None], min_item_level: int | None
) -> dict[str, SignupReadiness]:
    """Readiness for each sign-up character name (casefolded) that exactly one roster character has."""
    names = {name.split("-")[0].casefold() for name in characters if name}
    if not names:
        return {}
    model = BattlenetCharacter
    statement = select(model).where(model.in_roster.is_(True), func.lower(model.name).in_(list(names)))
    rows = list((await session.execute(statement)).scalars())
    counts = Counter(row.name.casefold() for row in rows)
    return {
        row.name.casefold(): SignupReadiness(
            slug=row.slug,
            level=row.level,
            item_level=row.item_level,
            spec=row.spec,
            below_minimum=min_item_level is not None and row.item_level is not None and row.item_level < min_item_level,
        )
        for row in rows
        if counts[row.name.casefold()] == 1
    }


def readiness_for(readiness: dict[str, SignupReadiness], character: str | None) -> SignupReadiness | None:
    """The readiness matching a sign-up's character name, if any."""
    return readiness.get(character.split("-")[0].casefold()) if character else None
