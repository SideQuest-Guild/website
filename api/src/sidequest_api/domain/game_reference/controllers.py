"""Profession, recipe, and class/spec art endpoints: public reference lookups from Battle.net.

``GET /api/professions/{id}``, ``GET /api/recipes/{id}`` and ``GET /api/game/classes`` have no query string, so
Cloudflare keeps them at the edge (``EDGE_REFERENCE_CACHE``); ``services.py`` also caches the whole catalog
in-process, since this reference data only changes with a game patch.
"""

from typing import Annotated

from litestar import Controller, get
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.params import Parameter
from sqlalchemy.ext.asyncio import AsyncSession
from wow import AsyncClient

from sidequest_api.domain.game_reference.services import (
    get_profession_skill_tier,
    get_recipe,
    list_classes,
    list_professions,
)
from sidequest_api.domain.items.dependencies import provide_items_service
from sidequest_api.domain.items.services import ItemsService
from sidequest_api.lib.game_data import provide_game_data
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_common.schemas import GameClassSchema, ProfessionSkillTierSchema, ProfessionSummary, RecipeDetail

_PROFESSION_ID = Annotated[int, Parameter(description="The profession's game ID.", gt=0)]
_RECIPE_ID = Annotated[int, Parameter(description="The recipe's game ID.", gt=0)]

# Battle.net changes professions, recipes and classes only with a game patch, same as items: an hour at the edge,
# then stale while one fetch refreshes it.
EDGE_REFERENCE_CACHE = ResponseHeader(name=EDGE_CACHE_HEADER, value="max-age=3600, stale-while-revalidate=86400")


class ProfessionsController(Controller):
    """``/api/professions``."""

    path = "/api/professions"
    tags = ["Recipes"]
    dependencies = {"game_data": Provide(provide_game_data)}

    @get(
        "/",
        operation_id="ListProfessions",
        opt=SKIP_SESSION,
        summary="List professions",
        description=(
            "Returns every profession: its type, icon, and skill tier id. Answers 503 if Battle.net is not "
            "configured or did not answer."
        ),
        response_description="Every profession.",
    )
    async def list_all(self, game_data: NamedDependency[AsyncClient]) -> list[ProfessionSummary]:
        return await list_professions(game_data)

    @get(
        "/{profession_id:int}",
        operation_id="GetProfession",
        response_headers=[EDGE_REFERENCE_CACHE],
        opt=SKIP_SESSION,
        summary="Get a profession's skill tier",
        description=(
            "Returns one profession's skill tier: its recipe categories, each with the recipes it holds. Answers "
            "404 if there's no such profession, 503 if Battle.net is not configured or did not answer."
        ),
        response_description="The profession's skill tier.",
    )
    async def get_one(
        self, game_data: NamedDependency[AsyncClient], profession_id: _PROFESSION_ID
    ) -> ProfessionSkillTierSchema:
        return await get_profession_skill_tier(game_data, profession_id)


class RecipesController(Controller):
    """``/api/recipes``."""

    path = "/api/recipes"
    tags = ["Recipes"]
    dependencies = {"game_data": Provide(provide_game_data), "items_service": Provide(provide_items_service)}

    @get(
        "/{recipe_id:int}",
        operation_id="GetRecipe",
        response_headers=[EDGE_REFERENCE_CACHE],
        opt=SKIP_SESSION,
        summary="Get a recipe",
        description=(
            "Returns one recipe: what it makes, its reagents, and the guild characters who know it (matched from "
            "the addon's crafter data by profession and recipe name). Answers 404 if there's no such recipe, 503 "
            "if Battle.net is not configured or did not answer."
        ),
        response_description="The recipe.",
    )
    async def get_one(
        self,
        game_data: NamedDependency[AsyncClient],
        items_service: NamedDependency[ItemsService],
        db_session: NamedDependency[AsyncSession],
        recipe_id: _RECIPE_ID,
    ) -> RecipeDetail:
        return await get_recipe(recipe_id, game_data, items_service, db_session)


class GameClassesController(Controller):
    """``/api/game``."""

    path = "/api/game"
    tags = ["Game data"]
    dependencies = {"game_data": Provide(provide_game_data)}

    @get(
        "/classes",
        operation_id="ListGameClasses",
        response_headers=[EDGE_REFERENCE_CACHE],
        opt=SKIP_SESSION,
        summary="List classes and specializations",
        description=(
            "Returns every playable class with its specializations and small icons, for the site's class/spec "
            "art. Answers 503 if Battle.net is not configured or did not answer."
        ),
        response_description="Every class.",
    )
    async def list_all(self, game_data: NamedDependency[AsyncClient]) -> list[GameClassSchema]:
        return await list_classes(game_data)
