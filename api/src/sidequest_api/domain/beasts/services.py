"""Tameable beasts from Battle.net: the Tameable beasts page's portrait grid and lookup.

The list (``list_beasts``/``list_families``) is built from one ``creatures.search`` call filtered to
``is_tameable`` and cached in-process, built once: Forever's tameable beasts (about 800) fit in one page at the
search API's maximum page size, so the catalog never needs to page. A single beast (``get_beast``) is instead read
straight from Battle.net's creature document, cached by id, so it still works for a beast the list catalog never
paged in. Either way, a beast's display render is fetched with bounded concurrency (an ``asyncio.Semaphore``, so a
page's worth of first-time fetches never opens more than a handful of connections to Battle.net at once) and
cached by display id for the life of the process (several beasts share a display, and classic beasts never change
outside a game patch).
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE
from wow import NotFoundError, WowError
from wow.search import MAX_PAGE_SIZE

from sidequest_common.schemas import BeastFamilySchema, BeastSchema

if TYPE_CHECKING:
    from wow import AsyncClient
    from wow.models import Creature

BATTLENET_UNREACHABLE = "Battle.net did not answer; try again in a minute"
_PLACEHOLDER_NAME = re.compile(r"^\[|\b(?:DNT|test)\b", re.IGNORECASE)
"""Blizzard's own unused and test creatures still flagged tameable: "[UNUSED] Zulian Tigress", "TEST WOLF (ALPHA
FIRST)", "Aidan's Test Creature DNT". No player can find them, so the catalog and lookup leave them out."""
_DISPLAY_MEDIA_CONCURRENCY = 8

_beasts: tuple[BeastSchema, ...] | None = None
_beasts_lock = asyncio.Lock()
_display_image_cache: dict[int, str | None] = {}
_display_semaphore = asyncio.Semaphore(_DISPLAY_MEDIA_CONCURRENCY)
_creature_cache: dict[int, Creature] = {}


async def _display_image_url(display_id: int, game_data: AsyncClient, semaphore: asyncio.Semaphore) -> str | None:
    """The ``zoom`` render URL for a creature display, cached process-wide. ``None`` if unavailable."""
    if display_id in _display_image_cache:
        return _display_image_cache[display_id]
    async with semaphore:
        try:
            media = await game_data.creatures.display_media(display_id)
        except WowError:
            _display_image_cache[display_id] = None
            return None
    url = next((asset.value for asset in media.assets if asset.key == "zoom"), None)
    _display_image_cache[display_id] = url
    return url


def _is_placeholder(name: str) -> bool:
    return _PLACEHOLDER_NAME.search(name) is not None


async def _build_beasts(game_data: AsyncClient) -> tuple[BeastSchema, ...]:
    """Every tameable beast from one search call, sorted by name, with bounded-concurrency display images."""
    try:
        page = await game_data.creatures.search(filters={"is_tameable": True}, page_size=MAX_PAGE_SIZE)
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    locale = game_data.locale
    hits = [
        hit
        for hit in page.results
        if not _is_placeholder(hit.data.name.get(locale) or next(iter(hit.data.name.values()), ""))
    ]
    display_ids = [hit.data.creature_displays[0].id if hit.data.creature_displays else None for hit in hits]
    image_urls = await asyncio.gather(
        *(
            _display_image_url(display_id, game_data, _display_semaphore)
            if display_id is not None
            else asyncio.sleep(0)
            for display_id in display_ids
        )
    )
    beasts = [
        BeastSchema(
            id=hit.data.id,
            name=hit.data.name.get(locale) or next(iter(hit.data.name.values()), ""),
            family_id=hit.data.family.id if hit.data.family is not None else None,
            family=(
                (hit.data.family.name.get(locale) or next(iter(hit.data.family.name.values()), ""))
                if hit.data.family is not None
                else None
            ),
            display_id=display_id,
            image_url=image_url,
        )
        for hit, display_id, image_url in zip(hits, display_ids, image_urls, strict=True)
    ]
    return tuple(sorted(beasts, key=lambda beast: beast.name.casefold()))


async def _catalog(game_data: AsyncClient) -> tuple[BeastSchema, ...]:
    """The tameable-beast catalog, built once per process (reused regardless of later Battle.net outages)."""
    global _beasts  # noqa: PLW0603 - one process-wide cache of Battle.net's reference data
    if _beasts is None:
        async with _beasts_lock:
            if _beasts is None:
                _beasts = await _build_beasts(game_data)
    return _beasts


def _matches(beast: BeastSchema, family_id: int | None, folded_q: str | None) -> bool:
    if family_id is not None and beast.family_id != family_id:
        return False
    return folded_q is None or folded_q in beast.name.casefold()


async def list_beasts(
    game_data: AsyncClient, *, q: str | None = None, family_id: int | None = None, limit: int | None = None
) -> list[BeastSchema]:
    """Every tameable beast, sorted by name; a prefix match of ``q`` sorts before a mid-name match.

    ``family_id`` keeps only beasts in that family. ``limit`` caps the result to its first entries, after filtering
    and sorting.
    """
    catalog = await _catalog(game_data)
    folded_q = q.casefold() if q else None
    matches = [beast for beast in catalog if _matches(beast, family_id, folded_q)]
    if folded_q:
        matches.sort(key=lambda beast: (not beast.name.casefold().startswith(folded_q), beast.name.casefold()))
    if limit is not None:
        matches = matches[:limit]
    return matches


async def _creature_doc(creature_id: int, game_data: AsyncClient) -> Creature:
    cached = _creature_cache.get(creature_id)
    if cached is not None:
        return cached
    creature = await game_data.creatures.get(creature_id)
    _creature_cache[creature_id] = creature
    return creature


async def get_beast(game_data: AsyncClient, creature_id: int) -> BeastSchema:
    """One tameable beast by its Battle.net creature id. 404 if Battle.net has no such creature, or it isn't tameable.

    Reads straight from Battle.net's own creature document, not the list catalog, in case ``search`` ever caps out
    before this one.
    """
    try:
        creature = await _creature_doc(creature_id, game_data)
    except NotFoundError as exc:
        msg = f"No creature {creature_id}"
        raise NotFoundException(msg) from exc
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    if not creature.is_tameable or _is_placeholder(creature.name):
        msg = f"Creature {creature_id} isn't a tameable beast"
        raise NotFoundException(msg)
    display_id = creature.creature_displays[0].id if creature.creature_displays else None
    image_url = await _display_image_url(display_id, game_data, _display_semaphore) if display_id is not None else None
    return BeastSchema(
        id=creature.id,
        name=creature.name,
        family_id=creature.family.id if creature.family is not None else None,
        family=creature.family.name if creature.family is not None else None,
        display_id=display_id,
        image_url=image_url,
    )


async def list_families(game_data: AsyncClient) -> list[BeastFamilySchema]:
    """Every beast family among tameable beasts, with how many tameable beasts belong to it, sorted by name."""
    catalog = await _catalog(game_data)
    counts: dict[int, int] = {}
    names: dict[int, str] = {}
    for beast in catalog:
        if beast.family_id is None:
            continue
        counts[beast.family_id] = counts.get(beast.family_id, 0) + 1
        names[beast.family_id] = beast.family or names.get(beast.family_id, "")
    families = [
        BeastFamilySchema(id=family_id, name=names[family_id], count=count) for family_id, count in counts.items()
    ]
    return sorted(families, key=lambda family: family.name.casefold())
