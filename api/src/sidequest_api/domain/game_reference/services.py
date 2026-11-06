"""Professions, recipes, and class/spec art from Battle.net.

The profession/recipe catalog (every profession's one skill tier, with every recipe's id and name) is built once
per process and kept forever: Forever's professions only change with a game patch. It also indexes recipes two
ways: by game id (for ``GET /api/recipes/{id}``'s profession lookup) and by ``(profession, name)`` casefolded (for
matching the addon's crafter data, which carries the game's recipe id and name, not Battle.net's, to Battle.net
recipe ids). The class/spec catalog is built once the same way, for the site's small class/spec icons.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE
from sqlalchemy import func, select
from wow import NotFoundError, WowError

from sidequest_common.models import CharacterProfession, CharacterRecipeLink, Member, ProfessionRecipe, WowCharacter
from sidequest_common.schemas import (
    GameClassSchema,
    GameSpecSchema,
    ProfessionSkillTierSchema,
    ProfessionSummary,
    RecipeCategorySchema,
    RecipeCraftedItem,
    RecipeCrafter,
    RecipeDetail,
    RecipeReagent,
    RecipeRefSchema,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from sqlalchemy.ext.asyncio import AsyncSession
    from wow import AsyncClient
    from wow.models import Media, Recipe

    from sidequest_api.domain.items.services import ItemsService

BATTLENET_UNREACHABLE = "Battle.net did not answer; try again in a minute"


@dataclass(frozen=True, slots=True)
class _CatalogRecipe:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class _CatalogCategory:
    name: str
    recipes: tuple[_CatalogRecipe, ...]


@dataclass(frozen=True, slots=True)
class _CatalogProfession:
    id: int
    name: str
    type: str
    icon_url: str | None
    skill_tier_id: int
    categories: tuple[_CatalogCategory, ...]


@dataclass(frozen=True, slots=True)
class _Catalog:
    professions: tuple[_CatalogProfession, ...]
    recipe_profession: dict[int, tuple[str, str]]
    recipe_by_name: dict[tuple[str, str], int]


_catalog: _Catalog | None = None
_catalog_lock = asyncio.Lock()
_classes: tuple[GameClassSchema, ...] | None = None
_classes_lock = asyncio.Lock()
_recipe_cache: dict[int, Recipe] = {}


async def _media_icon(media: Awaitable[Media]) -> str | None:
    """The ``icon`` asset's URL from a pending media fetch, or ``None`` if Battle.net has none or did not answer."""
    try:
        document = await media
    except WowError:
        return None
    return next((asset.value for asset in document.assets if asset.key == "icon"), None)


async def _catalog_profession(profession_id: int, game_data: AsyncClient) -> _CatalogProfession:
    """One profession with its icon and its (single) skill tier's categories of recipes."""
    profession = await game_data.professions.get(profession_id)
    tier_ref = profession.skill_tiers[0] if profession.skill_tiers else None
    # gather, not a TaskGroup: callers catch the WowError itself, which a TaskGroup would wrap in an ExceptionGroup.
    icon_url, tier = await asyncio.gather(
        _media_icon(game_data.professions.media(profession.id)),
        game_data.professions.skill_tier(profession.id, tier_ref.id) if tier_ref else asyncio.sleep(0),
    )
    categories = tuple(
        _CatalogCategory(
            name=category.name, recipes=tuple(_CatalogRecipe(id=r.id, name=r.name) for r in category.recipes)
        )
        for category in (tier.categories if tier is not None else ())
    )
    return _CatalogProfession(
        id=profession.id,
        name=profession.name,
        type=profession.type.type,
        icon_url=icon_url,
        skill_tier_id=tier_ref.id if tier_ref is not None else 0,
        categories=categories,
    )


async def _build_catalog(game_data: AsyncClient) -> _Catalog:
    index = await game_data.professions.index()
    professions = await asyncio.gather(*(_catalog_profession(ref.id, game_data) for ref in index.professions))
    recipe_profession: dict[int, tuple[str, str]] = {}
    recipe_by_name: dict[tuple[str, str], int] = {}
    for profession in professions:
        for category in profession.categories:
            for recipe in category.recipes:
                recipe_profession[recipe.id] = (profession.name, recipe.name)
                recipe_by_name[(profession.name.casefold(), recipe.name.casefold())] = recipe.id
    return _Catalog(professions=tuple(professions), recipe_profession=recipe_profession, recipe_by_name=recipe_by_name)


async def catalog(game_data: AsyncClient) -> _Catalog:
    """The profession/recipe catalog, built once per process (reused regardless of later Battle.net outages)."""
    global _catalog  # noqa: PLW0603 - one process-wide cache of Battle.net's reference data
    if _catalog is None:
        async with _catalog_lock:
            if _catalog is None:
                _catalog = await _build_catalog(game_data)
    return _catalog


async def list_professions(game_data: AsyncClient) -> list[ProfessionSummary]:
    """Every profession: id, name, type, icon and skill tier id."""
    data = await catalog(game_data)
    return [
        ProfessionSummary(id=p.id, name=p.name, type=p.type, icon_url=p.icon_url, skill_tier_id=p.skill_tier_id)
        for p in data.professions
    ]


async def get_profession_skill_tier(game_data: AsyncClient, profession_id: int) -> ProfessionSkillTierSchema:
    """One profession's skill tier: its categories and recipe refs. 404 if there's no such profession."""
    data = await catalog(game_data)
    profession = next((p for p in data.professions if p.id == profession_id), None)
    if profession is None:
        msg = f"No profession {profession_id}"
        raise NotFoundException(msg)
    return ProfessionSkillTierSchema(
        profession_id=profession.id,
        profession_name=profession.name,
        categories=[
            RecipeCategorySchema(
                name=category.name, recipes=[RecipeRefSchema(id=r.id, name=r.name) for r in category.recipes]
            )
            for category in profession.categories
        ],
    )


async def recipe_id_for(profession: str, name: str, game_data: AsyncClient | None) -> int | None:
    """The Battle.net recipe id matching a profession and casefolded recipe name, or ``None``.

    ``None`` whenever Battle.net is unconfigured, unreachable, or has no match: this is best-effort enrichment on
    the addon's own crafter data, never a reason to fail the request it decorates. The SDK raises ``WowError`` for
    every Battle.net failure, transport errors included (``APIConnectionError``).
    """
    if game_data is None:
        return None
    try:
        data = await catalog(game_data)
    except WowError:
        return None
    return data.recipe_by_name.get((profession.casefold(), name.casefold()))


async def _recipe_doc(recipe_id: int, game_data: AsyncClient) -> Recipe:
    cached = _recipe_cache.get(recipe_id)
    if cached is not None:
        return cached
    recipe = await game_data.recipes.get(recipe_id)
    _recipe_cache[recipe_id] = recipe
    return recipe


def _crafted_quantity_text(recipe: Recipe) -> str | None:
    quantity = recipe.crafted_quantity
    if quantity is None:
        return None
    if quantity.value is not None:
        return f"Makes {int(quantity.value)}"
    if quantity.minimum is not None and quantity.maximum is not None:
        return f"Makes {int(quantity.minimum)}-{int(quantity.maximum)}"
    return None


async def _item_quality(item_id: int, game_data: AsyncClient, items_service: ItemsService) -> str | None:
    try:
        item = await items_service.get_item(item_id, game_data)
    except NotFoundException, HTTPException:
        return None
    return item.quality


async def _recipe_crafters(session: AsyncSession, profession: str, recipe_name: str) -> list[RecipeCrafter]:
    """Guild characters who know this exact recipe (profession and casefolded name), never a substring match."""
    statement = (
        select(CharacterProfession, WowCharacter)
        .join(CharacterRecipeLink, CharacterRecipeLink.profession_id == CharacterProfession.id)
        .join(ProfessionRecipe, ProfessionRecipe.id == CharacterRecipeLink.recipe_id)
        .join(WowCharacter, WowCharacter.id == CharacterProfession.character_id)
        .where(func.lower(CharacterProfession.profession) == profession.casefold())
        .where(func.lower(ProfessionRecipe.name) == recipe_name.casefold())
    )
    rows = (await session.execute(statement)).all()
    member_ids = {character.member_id for _, character in rows if character.member_id is not None}
    members = (
        {
            member.id: member
            for member in (await session.execute(select(Member).where(Member.id.in_(member_ids)))).scalars().all()
        }
        if member_ids
        else {}
    )
    return [
        RecipeCrafter(
            character=character.key,
            member_id=character.member_id,
            member_name=members[character.member_id].display_name if character.member_id in members else None,
            skill=profession_row.skill,
        )
        for profession_row, character in rows
    ]


async def get_recipe(
    recipe_id: int, game_data: AsyncClient, items_service: ItemsService, session: AsyncSession
) -> RecipeDetail:
    """One recipe by its game ID: what it makes, its reagents, and the guild characters who know it."""
    try:
        recipe = await _recipe_doc(recipe_id, game_data)
    except NotFoundError as exc:
        msg = f"No recipe {recipe_id}"
        raise NotFoundException(msg) from exc
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    icon_url = await _media_icon(game_data.recipes.media(recipe_id))

    crafted_item = None
    if recipe.crafted_item is not None:
        quality = await _item_quality(recipe.crafted_item.id, game_data, items_service)
        crafted_item = RecipeCraftedItem(item_id=recipe.crafted_item.id, name=recipe.crafted_item.name, quality=quality)

    reagent_qualities = await asyncio.gather(
        *(_item_quality(r.reagent.id, game_data, items_service) for r in recipe.reagents)
    )
    reagents = [
        RecipeReagent(item_id=r.reagent.id, name=r.reagent.name, quantity=r.quantity, quality=quality)
        for r, quality in zip(recipe.reagents, reagent_qualities, strict=True)
    ]

    data = await catalog(game_data)
    match = data.recipe_profession.get(recipe_id)
    profession_name = match[0] if match is not None else None
    crafters = await _recipe_crafters(session, match[0], match[1]) if match is not None else []

    return RecipeDetail(
        recipe_id=recipe.id,
        name=recipe.name,
        description=recipe.description,
        rank=recipe.rank,
        profession=profession_name,
        icon_url=icon_url,
        crafted_item=crafted_item,
        crafted_quantity=_crafted_quantity_text(recipe),
        reagents=reagents,
        crafters=crafters,
    )


async def _class_art(class_id: int, game_data: AsyncClient) -> GameClassSchema:
    """One class with its icon and its specializations' icons."""
    cls = await game_data.playable_classes.get(class_id)
    icon_url, *spec_icons = await asyncio.gather(
        _media_icon(game_data.playable_classes.media(cls.id)),
        *(_media_icon(game_data.playable_specializations.media(spec.id)) for spec in cls.specializations),
    )
    specs = [
        GameSpecSchema(id=spec.id, name=spec.name, icon_url=spec_icon)
        for spec, spec_icon in zip(cls.specializations, spec_icons, strict=True)
    ]
    return GameClassSchema.model_validate(
        {"class": cls.name.casefold(), "name": cls.name, "icon_url": icon_url, "specs": specs}
    )


async def _build_classes(game_data: AsyncClient) -> tuple[GameClassSchema, ...]:
    index = await game_data.playable_classes.index()
    return tuple(await asyncio.gather(*(_class_art(ref.id, game_data) for ref in index.classes)))


async def list_classes(game_data: AsyncClient) -> list[GameClassSchema]:
    """Every playable class with its specializations and small art, built once per process."""
    global _classes  # noqa: PLW0603 - one process-wide cache of Battle.net's reference data
    if _classes is None:
        async with _classes_lock:
            if _classes is None:
                _classes = await _build_classes(game_data)
    return list(_classes)
