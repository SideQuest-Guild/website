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
    QuestRef,
    QuestReputationReward,
    QuestRequirementRef,
    QuestRewardItem,
    QuestRewardsSchema,
    QuestSchema,
    QuestSearchResult,
    QuestSummary,
)

if TYPE_CHECKING:
    from wow import AsyncClient
    from wow.models import Achievement, AchievementCriteria, Quest, QuestCategory, QuestCondition

BATTLENET_UNREACHABLE = "Battle.net did not answer; try again in a minute"
HIDDEN_CATEGORY = "Do Not Display"
"""Blizzard's own bucket for internal achievements; the game never shows it."""
# Quest text addresses the reader by placeholders the game fills in: {name}, {class}, {race}.
_QUEST_PLACEHOLDER = re.compile(r"\{(?:name|class|race)\}", re.IGNORECASE)
_MAX_CHAIN_DEPTH = 25
"""How far back `_quest_chain` walks required prerequisites before giving up."""
_LEADS_TO_CONCURRENCY = 8
"""Battle.net requests in flight at once while scanning a zone for `leads_to` follow-ups."""
_SEARCH_INDEX_CONCURRENCY = 8
"""Battle.net requests in flight at once while building the quest title search index."""

_quest_area_index: tuple[QuestAreaSummary, ...] | None = None
_quest_areas: dict[int, QuestAreaSchema] = {}
_quests: dict[int, QuestSchema] = {}
_raw_quests: dict[int, Quest] = {}
_quest_chains: dict[int, tuple[QuestRef, ...]] = {}
_quest_leads_to_cache: dict[int, tuple[QuestRef, ...]] = {}
_quest_title_index: tuple[QuestSearchResult, ...] | None = None
_quest_title_index_lock = asyncio.Lock()
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


async def _raw_quest(game_data: AsyncClient, quest_id: int) -> Quest:
    """The quest document from Battle.net, cached for the process. 404 if Battle.net has no such quest.

    Shared by `quest()`, `_quest_chain` and `_quest_leads_to` so walking a chain or scanning a zone never re-fetches
    a quest already seen this process.
    """
    cached = _raw_quests.get(quest_id)
    if cached is not None:
        return cached
    try:
        found = await game_data.quests.get(quest_id)
    except NotFoundError as exc:
        msg = f"No quest {quest_id}"
        raise NotFoundException(msg) from exc
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    _raw_quests[quest_id] = found
    return found


def _flatten_quest_condition(
    condition: QuestCondition,
    requires: list[QuestRequirementRef],
    excludes: list[QuestRef],
    *,
    group: int | None,
    next_group: list[int],
) -> None:
    """Walk one condition node into `requires`/`excludes`.

    A leaf (`target` set) is required unless `must_be_incomplete`, in which case it excludes. An `AND` flattens its
    children into the same group as its parent; an `OR` assigns its direct children a fresh shared group number, so
    a UI can say "one of these".
    """
    if condition.target is not None:
        if condition.must_be_incomplete:
            excludes.append(QuestRef(id=condition.target.id, title=condition.target.name))
        else:
            requires.append(QuestRequirementRef(id=condition.target.id, title=condition.target.name, group=group))
        return
    if condition.operator is not None and condition.operator.type == "OR":
        or_group = next_group[0]
        next_group[0] += 1
        for child in condition.conditions:
            _flatten_quest_condition(child, requires, excludes, group=or_group, next_group=next_group)
        return
    for child in condition.conditions:
        _flatten_quest_condition(child, requires, excludes, group=group, next_group=next_group)


def _quest_requirements(found: Quest) -> tuple[list[QuestRequirementRef], list[QuestRef]]:
    """A quest's prerequisites (`requires`) and lockouts (`excludes`), flattened from Battle.net's condition tree."""
    requires: list[QuestRequirementRef] = []
    excludes: list[QuestRef] = []
    condition = found.requirements.quests
    if condition is not None:
        _flatten_quest_condition(condition, requires, excludes, group=None, next_group=[0])
    return requires, excludes


async def _quest_chain(game_data: AsyncClient, quest_id: int, requires: list[QuestRequirementRef]) -> list[QuestRef]:
    """Earlier quests leading up to `quest_id`, earliest first.

    Follows the first required prerequisite back at each step, up to `_MAX_CHAIN_DEPTH` steps. Stops (without
    error) at a 404/503 or a quest already seen, so it is safe against cycles. Cached for the process.
    """
    cached = _quest_chains.get(quest_id)
    if cached is not None:
        return list(cached)
    chain: list[QuestRef] = []
    visited = {quest_id}
    current_requires = requires
    for _ in range(_MAX_CHAIN_DEPTH):
        if not current_requires:
            break
        prev_id = current_requires[0].id
        if prev_id in visited:
            break
        visited.add(prev_id)
        try:
            prev_raw = await _raw_quest(game_data, prev_id)
        except HTTPException:
            break
        chain.append(QuestRef(id=prev_raw.id, title=prev_raw.title))
        current_requires, _ = _quest_requirements(prev_raw)
    chain.reverse()
    _quest_chains[quest_id] = tuple(chain)
    return chain


async def _zone_quest_ids(game_data: AsyncClient, area_id: int) -> list[int]:
    """Every quest id in one zone, via the cached `quest_area` lookup."""
    try:
        area = await quest_area(game_data, area_id)
    except HTTPException:
        return []
    return [link.id for link in area.quests]


async def _follow_ups_in_zone(
    game_data: AsyncClient, zone_quest_ids: list[int], target_id: int, semaphore: asyncio.Semaphore
) -> list[Quest]:
    """Quest documents from `zone_quest_ids` whose requirements include `target_id`.

    Fetched with bounded concurrency through the shared `_raw_quest` cache. A quest that 404s or that Battle.net
    won't answer is skipped.
    """

    async def _fetch(quest_id: int) -> Quest | None:
        async with semaphore:
            try:
                return await _raw_quest(game_data, quest_id)
            except HTTPException:
                return None

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(_fetch(quest_id)) for quest_id in zone_quest_ids if quest_id != target_id]
    raws = (task.result() for task in tasks)
    return [raw for raw in raws if raw is not None and any(req.id == target_id for req in _quest_requirements(raw)[0])]


async def _quest_leads_to(game_data: AsyncClient, quest_id: int, area_id: int | None) -> list[QuestRef]:
    """Quests whose prerequisites include `quest_id`.

    Scans its zone, then the zones of any direct follow-ups found there (one hop out), bounding the number of
    Battle.net requests. See `QuestSchema.leads_to` for the resulting limitation. Cached for the process.
    """
    cached = _quest_leads_to_cache.get(quest_id)
    if cached is not None:
        return list(cached)
    if area_id is None:
        _quest_leads_to_cache[quest_id] = ()
        return []
    semaphore = asyncio.Semaphore(_LEADS_TO_CONCURRENCY)
    found = await _follow_ups_in_zone(game_data, await _zone_quest_ids(game_data, area_id), quest_id, semaphore)
    other_zones = {raw.area.id for raw in found if raw.area is not None and raw.area.id != area_id}
    for zone_id in other_zones:
        zone_quest_ids = await _zone_quest_ids(game_data, zone_id)
        found.extend(await _follow_ups_in_zone(game_data, zone_quest_ids, quest_id, semaphore))
    seen: set[int] = set()
    result: list[QuestRef] = []
    for raw in found:
        if raw.id not in seen:
            seen.add(raw.id)
            result.append(QuestRef(id=raw.id, title=raw.title))
    result.sort(key=lambda ref: ref.id)
    _quest_leads_to_cache[quest_id] = tuple(result)
    return result


def _quest_schema(
    found: Quest,
    *,
    requires: list[QuestRequirementRef],
    excludes: list[QuestRef],
    chain: list[QuestRef],
    leads_to: list[QuestRef],
) -> QuestSchema:
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
        requires=requires,
        excludes=excludes,
        chain=chain,
        leads_to=leads_to,
    )


async def quest(game_data: AsyncClient, quest_id: int) -> QuestSchema:
    """One quest by its game ID, with its chain, requirements and follow-ups. 404 if Battle.net has no such quest."""
    cached = _quests.get(quest_id)
    if cached is not None:
        return cached
    found = await _raw_quest(game_data, quest_id)
    requires, excludes = _quest_requirements(found)
    chain = await _quest_chain(game_data, quest_id, requires)
    leads_to = await _quest_leads_to(game_data, quest_id, found.area.id if found.area is not None else None)
    result = _quest_schema(found, requires=requires, excludes=excludes, chain=chain, leads_to=leads_to)
    _quests[quest_id] = result
    return result


async def _category_quests(game_data: AsyncClient, semaphore: asyncio.Semaphore) -> list[QuestSearchResult]:
    """Every quest each quest category lists, its category standing in for a zone. Empty if Battle.net has none."""

    async def _fetch_category(category_id: int) -> QuestCategory | None:
        async with semaphore:
            try:
                return await game_data.quest_categories.get(category_id)
            except NotFoundError:
                return None

    try:
        category_index = await game_data.quest_categories.index()
        categories = await asyncio.gather(*(_fetch_category(ref.id) for ref in category_index.categories))
    except NotFoundError:
        return []
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    return [
        QuestSearchResult(id=link.id, title=link.name, area=category.category)
        for category in categories
        if category is not None
        for link in category.quests
    ]


async def _build_quest_title_index(game_data: AsyncClient) -> tuple[QuestSearchResult, ...]:
    """Every quest's id, title and zone, for name search.

    Built once per process from every quest zone's quest list (~139 zones), then every quest category's (~33), which
    holds the quests no zone lists, such as class and profession quests; those show their category in place of a zone.
    Guarded against concurrent first builds.
    """
    global _quest_title_index  # noqa: PLW0603 - one process-wide cache of Battle.net's reference data
    if _quest_title_index is not None:
        return _quest_title_index
    async with _quest_title_index_lock:
        if _quest_title_index is not None:
            return _quest_title_index
        areas = await quest_areas(game_data)
        semaphore = asyncio.Semaphore(_SEARCH_INDEX_CONCURRENCY)

        async def _fetch(area: QuestAreaSummary) -> tuple[str, QuestAreaSchema]:
            async with semaphore:
                return area.name, await quest_area(game_data, area.id)

        area_pairs = await asyncio.gather(*(_fetch(area) for area in areas))
        seen: dict[int, QuestSearchResult] = {}
        for area_name, area_schema in area_pairs:
            for link in area_schema.quests:
                seen.setdefault(link.id, QuestSearchResult(id=link.id, title=link.title, area=area_name))
        for entry in await _category_quests(game_data, semaphore):
            seen.setdefault(entry.id, entry)
        _quest_title_index = tuple(seen.values())
    return _quest_title_index


def _search_rank(title: str, query: str) -> tuple[int, int, str]:
    """An exact match ranks first, then a prefix, then any other substring; shorter titles break ties within a tier."""
    lowered = title.lower()
    if lowered == query:
        tier = 0
    elif lowered.startswith(query):
        tier = 1
    else:
        tier = 2
    return (tier, len(title), lowered)


async def quest_search(game_data: AsyncClient, query: str, limit: int) -> list[QuestSearchResult]:
    """Quests whose title contains `query` (case-insensitive), best matches first."""
    needle = query.strip().lower()
    if not needle:
        return []
    index = await _build_quest_title_index(game_data)
    matches = [entry for entry in index if needle in entry.title.lower()]
    matches.sort(key=lambda entry: _search_rank(entry.title, needle))
    return matches[:limit]


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
