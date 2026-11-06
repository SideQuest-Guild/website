"""Quest and achievement reference lookups from Battle.net: zones, quests, achievement categories and achievements.

Pure reference data (Battle.net only changes it with a game patch, and each deploy restarts the process), so a
plain process-wide cache is enough: unlike ``domain/items/services.py``, there is no Postgres table and no data
version to track. Cloudflare edge-caches the routes themselves (``EDGE_REFERENCE_CACHE``, routes carry no query
string), so this cache only saves the Battle.net round trip for the first visitor per process.
"""

import asyncio
import re
from typing import TYPE_CHECKING

from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE
from wow import NotFoundError, WowError

from sidequest_common.schemas import (
    AchievementCategorySchema,
    AchievementCategorySummary,
    AchievementCategoryTree,
    AchievementCriterion,
    AchievementSchema,
    AchievementSummary,
    QuestAreaSchema,
    QuestAreaSummary,
    QuestReputationReward,
    QuestRewardItem,
    QuestRewardsSchema,
    QuestSchema,
    QuestSummary,
)

if TYPE_CHECKING:
    from wow import AsyncClient
    from wow.models import Achievement, AchievementCriteria, Quest

BATTLENET_UNREACHABLE = "Battle.net did not answer; try again in a minute"
HIDDEN_CATEGORY = "Do Not Display"
"""Blizzard's own bucket for internal achievements; the game never shows it."""
# Quest text addresses the reader by placeholders the game fills in: {name}, {class}, {race}.
_QUEST_PLACEHOLDER = re.compile(r"\{(?:name|class|race)\}", re.IGNORECASE)

_quest_area_index: tuple[QuestAreaSummary, ...] | None = None
_quest_areas: dict[int, QuestAreaSchema] = {}
_quests: dict[int, QuestSchema] = {}
_achievement_category_tree: tuple[AchievementCategoryTree, ...] | None = None
_achievement_categories: dict[int, AchievementCategorySchema] = {}
_achievements: dict[int, AchievementSchema] = {}


async def quest_areas(game_data: AsyncClient) -> list[QuestAreaSummary]:
    """Every quest zone, alphabetical, cached for the process."""
    global _quest_area_index  # noqa: PLW0603 - one process-wide cache of Battle.net's reference data
    if _quest_area_index is None:
        try:
            index = await game_data.quest_areas.index()
        except WowError as exc:
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
        _quest_area_index = tuple(
            sorted((QuestAreaSummary(id=area.id, name=area.name) for area in index.areas), key=lambda area: area.name)
        )
    return list(_quest_area_index)


async def quest_area(game_data: AsyncClient, area_id: int) -> QuestAreaSchema:
    """One quest zone and its quests, cached for the process. 404 if Battle.net has no such zone."""
    cached = _quest_areas.get(area_id)
    if cached is not None:
        return cached
    try:
        area = await game_data.quest_areas.get(area_id)
    except NotFoundError as exc:
        msg = f"No quest area {area_id}"
        raise NotFoundException(msg) from exc
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    result = QuestAreaSchema(
        id=area.id, name=area.area, quests=[QuestSummary(id=link.id, title=link.name) for link in area.quests]
    )
    _quest_areas[area_id] = result
    return result


def _quest_schema(found: Quest) -> QuestSchema:
    rewards = found.rewards
    items = [
        QuestRewardItem(item_id=line.item.id, name=line.item.name)
        for line in (rewards.items.items if rewards.items is not None else ())
    ]
    reputations = [QuestReputationReward(faction=line.reward.name, value=line.value) for line in rewards.reputations]
    return QuestSchema(
        id=found.id,
        title=found.title,
        description=_QUEST_PLACEHOLDER.sub("adventurer", found.description) if found.description else found.description,
        area=found.area.name if found.area is not None else None,
        category=found.category.name if found.category is not None else None,
        type=found.type.name if found.type is not None else None,
        min_level=found.requirements.min_character_level,
        max_level=found.requirements.max_character_level,
        is_repeatable=found.is_repeatable,
        is_daily=found.is_daily,
        is_weekly=found.is_weekly,
        rewards=QuestRewardsSchema(
            experience=rewards.experience,
            money=rewards.money.units.copper if rewards.money is not None else None,
            items=items,
            reputations=reputations,
        ),
    )


async def quest(game_data: AsyncClient, quest_id: int) -> QuestSchema:
    """One quest by its game ID, cached for the process. 404 if Battle.net has no such quest."""
    cached = _quests.get(quest_id)
    if cached is not None:
        return cached
    try:
        found = await game_data.quests.get(quest_id)
    except NotFoundError as exc:
        msg = f"No quest {quest_id}"
        raise NotFoundException(msg) from exc
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    result = _quest_schema(found)
    _quests[quest_id] = result
    return result


async def achievement_categories(game_data: AsyncClient) -> list[AchievementCategoryTree]:
    """Every root achievement category with its subcategories, display order, cached for the process."""
    global _achievement_category_tree  # noqa: PLW0603 - one process-wide cache of Battle.net's reference data
    if _achievement_category_tree is None:
        try:
            index = await game_data.achievement_categories.index()
            roots = await asyncio.gather(
                *(game_data.achievement_categories.get(ref.id) for ref in index.root_categories)
            )
        except WowError as exc:
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
        _achievement_category_tree = tuple(
            AchievementCategoryTree(
                id=root.id,
                name=root.name,
                children=[
                    AchievementCategorySummary(id=ref.id, name=ref.name)
                    for ref in root.subcategories
                    if ref.name != HIDDEN_CATEGORY
                ],
            )
            for root in sorted(roots, key=lambda root: root.display_order)
            if root.name != HIDDEN_CATEGORY
        )
    return list(_achievement_category_tree)


def _achievement_schema(found: Achievement, *, icon_url: str | None) -> AchievementSchema:
    return AchievementSchema(
        id=found.id,
        name=found.name,
        description=found.description,
        points=found.points,
        icon_url=icon_url,
        category=found.category.name,
        reward_description=found.reward_description,
        criteria=_criterion(found.criteria),
    )


def _criterion(criteria: AchievementCriteria) -> AchievementCriterion:
    return AchievementCriterion(
        description=criteria.description,
        amount=criteria.amount,
        children=[_criterion(child) for child in criteria.child_criteria],
    )


async def _cached_achievement(game_data: AsyncClient, achievement_id: int) -> AchievementSummary:
    """The achievement's name and points for a category listing, icon-less (cheap: no media fetch per entry).

    Shares ``_achievements`` with ``achievement()`` below, so browsing a category first costs an achievement
    detail page no extra Battle.net request beyond its icon.
    """
    cached = _achievements.get(achievement_id)
    if cached is None:
        found = await game_data.achievements.get(achievement_id)
        cached = _achievement_schema(found, icon_url=None)
        _achievements[achievement_id] = cached
    return AchievementSummary(id=cached.id, name=cached.name, points=cached.points, icon_url=cached.icon_url)


async def achievement_category(game_data: AsyncClient, category_id: int) -> AchievementCategorySchema:
    """One achievement category and its achievements with points, cached for the process. 404 if unknown."""
    cached = _achievement_categories.get(category_id)
    if cached is not None:
        return cached
    try:
        category = await game_data.achievement_categories.get(category_id)
    except NotFoundError as exc:
        msg = f"No achievement category {category_id}"
        raise NotFoundException(msg) from exc
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    try:
        achievements = await asyncio.gather(*(_cached_achievement(game_data, ref.id) for ref in category.achievements))
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    result = AchievementCategorySchema(id=category.id, name=category.name, achievements=list(achievements))
    _achievement_categories[category_id] = result
    return result


async def _achievement_icon(game_data: AsyncClient, achievement_id: int) -> str | None:
    """The achievement's icon URL, or ``None`` if Battle.net has no icon for it or did not answer."""
    try:
        media = await game_data.achievements.media(achievement_id)
    except WowError:
        return None
    return next((asset.value for asset in media.assets if asset.key == "icon"), None)


async def achievement(game_data: AsyncClient, achievement_id: int) -> AchievementSchema:
    """One achievement by its game ID, with its icon. 404 if Battle.net has no such achievement."""
    cached = _achievements.get(achievement_id)
    if cached is not None and cached.icon_url is not None:
        return cached
    if cached is None:
        try:
            found = await game_data.achievements.get(achievement_id)
        except NotFoundError as exc:
            msg = f"No achievement {achievement_id}"
            raise NotFoundException(msg) from exc
        except WowError as exc:
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
        cached = _achievement_schema(found, icon_url=None)
    icon_url = await _achievement_icon(game_data, achievement_id)
    result = cached.model_copy(update={"icon_url": icon_url})
    _achievements[achievement_id] = result
    return result
