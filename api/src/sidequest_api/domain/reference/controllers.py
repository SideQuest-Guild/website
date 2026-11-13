"""Quest and achievement endpoints: public reference lookups from Battle.net's Quest and Achievement APIs.

Every route but quest search has no query string, so Cloudflare keeps those at the edge (``EDGE_REFERENCE_CACHE``);
the API also caches each lookup in-process (``services.py``), since this reference data only changes with a game
patch. Search answers differ by query string, which Cloudflare's cache rule ignores, so it is never edge-cached;
its in-process title index is built once and reused instead.
"""

from typing import Annotated

from litestar import Controller, get
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.params import Parameter
from wow import AsyncClient

from sidequest_api.domain.reference.services import (
    achievement,
    achievement_categories,
    achievement_category,
    quest,
    quest_area,
    quest_areas,
    quest_search,
)
from sidequest_api.lib.game_data import provide_game_data
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_common.schemas import (
    QUEST_SEARCH_LIMIT,
    QUEST_SEARCH_MIN_LENGTH,
    AchievementCategorySchema,
    AchievementCategoryTree,
    AchievementSchema,
    QuestAreaSchema,
    QuestAreaSummary,
    QuestSchema,
    QuestSearchResult,
)

_QUEST_ID = Annotated[int, Parameter(description="The quest's game ID.", gt=0)]
_AREA_ID = Annotated[int, Parameter(description="The quest area's game ID.", gt=0)]
_ACHIEVEMENT_ID = Annotated[int, Parameter(description="The achievement's game ID.", gt=0)]
_CATEGORY_ID = Annotated[int, Parameter(description="The achievement category's game ID.", gt=0)]

# Battle.net changes quests and achievements only with a game patch, same as items (domain/items/controllers.py):
# an hour at the edge, then stale while one fetch refreshes it.
EDGE_REFERENCE_CACHE = ResponseHeader(name=EDGE_CACHE_HEADER, value="max-age=3600, stale-while-revalidate=86400")


class QuestsController(Controller):
    """``/api/quests``."""

    path = "/api/quests"
    tags = ["Quests"]
    dependencies = {"game_data": Provide(provide_game_data)}

    @get(
        "/areas",
        operation_id="ListQuestAreas",
        response_headers=[EDGE_REFERENCE_CACHE],
        opt=SKIP_SESSION,
        summary="List quest areas",
        description=(
            "Returns every quest zone Battle.net knows, for browsing to its quests. Answers 503 if Battle.net is "
            "not configured or did not answer."
        ),
        response_description="Every quest zone.",
    )
    async def list_areas(self, game_data: NamedDependency[AsyncClient]) -> list[QuestAreaSummary]:
        return await quest_areas(game_data)

    @get(
        "/areas/{area_id:int}",
        operation_id="GetQuestArea",
        response_headers=[EDGE_REFERENCE_CACHE],
        opt=SKIP_SESSION,
        summary="Get a quest area",
        description=(
            "Returns one quest zone and the quests that take place there. Answers 404 if Battle.net has no such "
            "zone, 503 if Battle.net is not configured or did not answer."
        ),
        response_description="The quest zone and its quests.",
    )
    async def get_area(self, game_data: NamedDependency[AsyncClient], area_id: _AREA_ID) -> QuestAreaSchema:
        return await quest_area(game_data, area_id)

    @get(
        "/search",
        operation_id="SearchQuests",
        opt=SKIP_SESSION,
        summary="Search quests",
        description=(
            "Finds quests with `q` in their title, case-insensitive, best matches first (an exact or prefix match "
            "before any other substring match). Battle.net has no quest name search, so this is built from every "
            "quest zone's quest list and kept in memory for the process. Answers 503 if Battle.net is not "
            "configured or did not answer."
        ),
        response_description="Matching quests, best match first.",
    )
    async def search(
        self,
        game_data: NamedDependency[AsyncClient],
        q: Annotated[
            str,
            Parameter(description="Text to find in quest titles.", min_length=QUEST_SEARCH_MIN_LENGTH, max_length=80),
        ],
        limit: Annotated[int, Parameter(description="The most results to return.", ge=1, le=QUEST_SEARCH_LIMIT)] = 10,
    ) -> list[QuestSearchResult]:
        return await quest_search(game_data, q, limit)

    @get(
        "/{quest_id:int}",
        operation_id="GetQuest",
        response_headers=[EDGE_REFERENCE_CACHE],
        opt=SKIP_SESSION,
        summary="Get a quest",
        description=(
            "Returns one quest by its game ID: its description, zone, category, type, level requirements and "
            "rewards, plus the other quests it requires, excludes, leads to and the chain leading up to it. "
            "Description placeholders like `{class}` appear as Battle.net sends them. Answers 404 if Battle.net "
            "has no such quest, 503 if Battle.net is not configured or did not answer."
        ),
        response_description="The quest.",
    )
    async def get_quest(self, game_data: NamedDependency[AsyncClient], quest_id: _QUEST_ID) -> QuestSchema:
        return await quest(game_data, quest_id)


class AchievementsController(Controller):
    """``/api/achievements``."""

    path = "/api/achievements"
    tags = ["Achievements"]
    dependencies = {"game_data": Provide(provide_game_data)}

    @get(
        "/categories",
        operation_id="ListAchievementCategories",
        response_headers=[EDGE_REFERENCE_CACHE],
        opt=SKIP_SESSION,
        summary="List achievement categories",
        description=(
            "Returns every root achievement category with its subcategories, for browsing to its achievements. "
            "Answers 503 if Battle.net is not configured or did not answer."
        ),
        response_description="Every root achievement category and its children.",
    )
    async def list_categories(self, game_data: NamedDependency[AsyncClient]) -> list[AchievementCategoryTree]:
        return await achievement_categories(game_data)

    @get(
        "/categories/{category_id:int}",
        operation_id="GetAchievementCategory",
        response_headers=[EDGE_REFERENCE_CACHE],
        opt=SKIP_SESSION,
        summary="Get an achievement category",
        description=(
            "Returns one achievement category and the achievements in it, each with its points. Answers 404 if "
            "Battle.net has no such category, 503 if Battle.net is not configured or did not answer."
        ),
        response_description="The achievement category and its achievements.",
    )
    async def get_category(
        self, game_data: NamedDependency[AsyncClient], category_id: _CATEGORY_ID
    ) -> AchievementCategorySchema:
        return await achievement_category(game_data, category_id)

    @get(
        "/{achievement_id:int}",
        operation_id="GetAchievement",
        response_headers=[EDGE_REFERENCE_CACHE],
        opt=SKIP_SESSION,
        summary="Get an achievement",
        description=(
            "Returns one achievement by its game ID: its description, points, icon, category, reward text and "
            "its criteria tree. Answers 404 if Battle.net has no such achievement, 503 if Battle.net is not "
            "configured or did not answer."
        ),
        response_description="The achievement.",
    )
    async def get_achievement(
        self, game_data: NamedDependency[AsyncClient], achievement_id: _ACHIEVEMENT_ID
    ) -> AchievementSchema:
        return await achievement(game_data, achievement_id)
