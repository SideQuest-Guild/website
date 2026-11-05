"""Item lookups: Postgres first, Battle.net when an item is missing or Battle.net serves a newer data version.

Battle.net names its data version in each link's ``namespace`` (``static-1.60.1_70399-forever-us``). The newest one
this process has seen is kept in ``_data_version``; a stored item from an older version is fetched again on its next
read. If Battle.net fails, a stored item is served as it is.
"""

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE
from wow import NotFoundError, WowError

from sidequest_common.models import BattlenetItem
from sidequest_common.schemas import ITEM_SEARCH_PAGE_SIZE, ItemSearchPage, ItemSearchResult

if TYPE_CHECKING:
    from wow import AsyncClient
    from wow.models import Item, ItemPreview, Link

SEARCH_CACHE_SECONDS = 600
SEARCH_CACHE_MAX = 500
BATTLENET_UNREACHABLE = "Battle.net did not answer; try again in a minute"

_data_version: str | None = None
_search_cache: dict[tuple[str, int, tuple[str, ...], str | None], tuple[float, ItemSearchPage]] = {}


def _seen(link: Link) -> str:
    """Remember the data version named in ``link`` as the newest seen, and return it."""
    global _data_version  # noqa: PLW0603 - one process-wide notion of Battle.net's current data version
    version = parse_qs(urlsplit(link.href).query).get("namespace", [""])[0]
    _data_version = version
    return version


def _heading_lines(preview: ItemPreview) -> list[str]:
    """Item level, binding, uniqueness and slot: the lines under an item's name."""
    lines = [
        line
        for line in (
            preview.name_description.display_string if preview.name_description is not None else None,
            preview.level.display_string if preview.level is not None else None,
            preview.binding.name if preview.binding is not None else None,
            preview.unique_equipped,
        )
        if line is not None
    ]
    slot = preview.inventory_type.name if preview.inventory_type.type != "NON_EQUIP" else ""
    subclass = "" if preview.is_subclass_hidden else preview.item_subclass.name
    if slot or subclass:
        lines.append(" · ".join(part for part in (slot, subclass) if part))
    return lines


def _weapon_lines(preview: ItemPreview) -> list[str]:
    """Damage, speed and damage per second, for a weapon."""
    weapon = preview.weapon
    if weapon is None:
        return []
    optional = (weapon.attack_speed, weapon.dps)
    return [weapon.damage.display_string, *(value.display_string for value in optional if value is not None)]


def _requirement_lines(preview: ItemPreview) -> list[str]:
    """What a character needs to use the item: class, race, level, skill, reputation and so on."""
    requirements = preview.requirements
    if requirements is None:
        return []
    return [
        requirement.display_string
        for requirement in (
            requirements.playable_classes,
            requirements.playable_races,
            requirements.level,
            requirements.skill,
            requirements.reputation,
            requirements.ability,
            requirements.faction,
            requirements.holiday,
        )
        if requirement is not None
    ]


def _set_lines(preview: ItemPreview) -> list[str]:
    """The item set: its name, its pieces and its bonuses."""
    item_set = preview.set_
    if item_set is None:
        return []
    pieces = (f"  {piece.item.name}" for piece in item_set.items)
    return [item_set.display_string, *pieces, *(effect.display_string for effect in item_set.effects)]


def tooltip_lines(preview: ItemPreview) -> list[str]:
    """The text lines of an item's in-game tooltip below its name, in the order the game shows them."""
    armor = (armor.display.display_string for armor in (preview.armor, preview.shield_block) if armor is not None)
    lines = [
        *_heading_lines(preview),
        *_weapon_lines(preview),
        *armor,
        *(stat.display.display_string for stat in preview.stats if not stat.is_hidden),
    ]
    if preview.durability is not None:
        lines.append(preview.durability.display_string)
    lines.extend(_requirement_lines(preview))
    lines.extend(spell.description for spell in preview.spells)
    lines.extend(_set_lines(preview))
    if preview.item_starts_quest is not None:
        lines.append(preview.item_starts_quest.display_string)
    if preview.description:
        lines.append(f'"{preview.description}"')
    return lines


class BattlenetItemsRepository(SQLAlchemyAsyncRepository[BattlenetItem]):
    """Battle.net item persistence."""

    model_type = BattlenetItem


class ItemsService(SQLAlchemyAsyncRepositoryService[BattlenetItem]):
    """Items by game ID, and item search."""

    repository_type = BattlenetItemsRepository

    async def get_item(self, item_id: int, game_data: AsyncClient) -> BattlenetItem:
        """The item, from Postgres if it is current, else fetched from Battle.net and stored. 404 if no such item."""
        stored = await self.get_one_or_none(item_id=item_id)
        if stored is not None and (_data_version is None or stored.data_version == _data_version):
            return stored
        try:
            item = await game_data.items.get(item_id)
        except NotFoundError as exc:
            if stored is not None:
                return stored
            msg = f"No item {item_id}"
            raise NotFoundException(msg) from exc
        except WowError as exc:
            if stored is not None:
                return stored
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
        icon_url = await self._icon_url(item, game_data)
        values = self._values(item, icon_url)
        if stored is None:
            try:
                return await self.create(BattlenetItem(**values), auto_commit=True)
            except IntegrityError:
                # Another request stored the same item first; theirs is as fresh as ours.
                await self.repository.session.rollback()
                return await self.get_one(item_id=item_id)
        for field, value in values.items():
            setattr(stored, field, value)
        return await self.update(stored, auto_commit=True)

    @staticmethod
    async def _icon_url(item: Item, game_data: AsyncClient) -> str | None:
        """The item's icon URL, or ``None`` if Battle.net has no icon for it or did not answer."""
        try:
            media = await game_data.items.media(item.id)
        except WowError:
            return None
        return next((asset.value for asset in media.assets if asset.key == "icon"), None)

    @staticmethod
    def _values(item: Item, icon_url: str | None) -> dict[str, object]:
        preview = item.preview_item
        return {
            "item_id": item.id,
            "name": item.name,
            "quality": item.quality.type,
            "quality_name": item.quality.name,
            "item_class": item.item_class.name,
            "item_subclass": item.item_subclass.name,
            "inventory_type": item.inventory_type.type,
            "inventory_type_name": item.inventory_type.name,
            "item_level": item.level,
            "required_level": item.required_level,
            "sell_price": item.sell_price,
            "is_equippable": item.is_equippable,
            "icon_url": icon_url,
            "tooltip": tooltip_lines(preview),
            "data_version": _seen(item.links.self_),
            "fetched_at": datetime.now(UTC),
        }


async def search_items(
    game_data: AsyncClient, query: str, *, page: int, qualities: tuple[str, ...], slot: str | None
) -> ItemSearchPage:
    """One page of items with a whole word of ``query`` in their name (Battle.net stems words), cached ten minutes."""
    key = (query.casefold(), page, qualities, slot)
    cached = _search_cache.get(key)
    if cached is not None and time.monotonic() - cached[0] < SEARCH_CACHE_SECONDS:
        return cached[1]
    filters: dict[str, str | list[str]] = {}
    if qualities:
        filters["quality.type"] = list(qualities)
    if slot is not None:
        filters["inventory_type.type"] = slot
    try:
        found = await game_data.items.search(
            name=query,
            filters=filters,
            order_by=["required_level:desc", "id"],
            page=page,
            page_size=ITEM_SEARCH_PAGE_SIZE,
        )
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    locale = game_data.locale
    results = [
        ItemSearchResult(
            item_id=hit.data.id,
            name=hit.data.name.get(locale) or next(iter(hit.data.name.values()), ""),
            quality=hit.data.quality.type,
            quality_name=hit.data.quality.name.get(locale, hit.data.quality.type),
            inventory_type=hit.data.inventory_type.type,
            inventory_type_name=hit.data.inventory_type.name.get(locale, hit.data.inventory_type.type),
            item_level=hit.data.level,
            required_level=hit.data.required_level,
        )
        for hit in found.results
    ]
    if found.results:
        _seen(found.results[0].key)
    result = ItemSearchPage(page=found.page, page_count=found.page_count, results=results)
    if len(_search_cache) >= SEARCH_CACHE_MAX:
        _search_cache.pop(next(iter(_search_cache)))
    _search_cache[key] = (time.monotonic(), result)
    return result
