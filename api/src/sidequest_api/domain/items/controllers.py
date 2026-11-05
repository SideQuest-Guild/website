"""Item endpoints: public item lookup and item search, from Battle.net's Item API.

``GET /api/items/{item_id}`` is the same for every visitor and has no query string, so Cloudflare may keep it at the
edge. Search answers differ by query string, which Cloudflare's cache rule ignores, so search is never edge-cached;
the API caches each search for ten minutes instead.
"""

from typing import Annotated

from litestar import Controller, get
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.params import Parameter
from wow import AsyncClient

from sidequest_api.domain.items.dependencies import provide_items_service
from sidequest_api.domain.items.services import ItemsService, search_items
from sidequest_api.lib.game_data import provide_game_data
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_common.schemas import ITEM_SEARCH_MIN_LENGTH, ItemQuality, ItemSchema, ItemSearchPage

# Battle.net changes item data only with a game patch: an hour at the edge, then stale while one fetch refreshes it.
EDGE_ITEM_CACHE = ResponseHeader(name=EDGE_CACHE_HEADER, value="max-age=3600, stale-while-revalidate=86400")
# Battle.net returns at most 1,000 results, which is 20 pages of 50.
MAX_SEARCH_PAGE = 20
_SLOT = r"^[A-Z_0-9]+$"


class ItemsController(Controller):
    """``/api/items``."""

    path = "/api/items"
    tags = ["Items"]
    dependencies = {"items_service": Provide(provide_items_service), "game_data": Provide(provide_game_data)}

    @get(
        "/{item_id:int}",
        operation_id="GetItem",
        response_headers=[EDGE_ITEM_CACHE],
        opt=SKIP_SESSION,
        summary="Get an item",
        description=(
            "Returns one item by its game ID: quality, slot, levels, icon and the lines of its in-game tooltip. "
            "Answers 503 if Battle.net is not configured, or did not answer and the item was never stored."
        ),
        response_description="The item.",
    )
    async def get_item(
        self,
        items_service: NamedDependency[ItemsService],
        game_data: NamedDependency[AsyncClient],
        item_id: Annotated[int, Parameter(description="The item's game ID.", gt=0)],
    ) -> ItemSchema:
        return ItemSchema.model_validate(await items_service.get_item(item_id, game_data))

    @get(
        "/",
        operation_id="SearchItems",
        opt=SKIP_SESSION,
        summary="Search items",
        description=(
            "Finds items with a whole word of `q` in their name, highest required level first, 50 to a page. "
            "Battle.net matches English word stems, so `bless` finds Blessed, but `thund` finds nothing. It stops "
            "at 1,000 results. Answers 503 if Battle.net is not configured or did not answer."
        ),
        response_description="One page of matching items.",
    )
    async def search(
        self,
        game_data: NamedDependency[AsyncClient],
        q: Annotated[
            str, Parameter(description="Text to find in item names.", min_length=ITEM_SEARCH_MIN_LENGTH, max_length=100)
        ],
        page: Annotated[int, Parameter(description="The page, starting at 1.", ge=1, le=MAX_SEARCH_PAGE)] = 1,
        quality: Annotated[
            list[ItemQuality] | None,
            Parameter(description="Only these qualities. Repeat the parameter for more than one."),
        ] = None,
        slot: Annotated[
            str | None, Parameter(description="Only this slot, such as `TWOHWEAPON`.", pattern=_SLOT)
        ] = None,
    ) -> ItemSearchPage:
        qualities = tuple(sorted({str(value) for value in quality or ()}))
        return await search_items(game_data, q.strip(), page=page, qualities=qualities, slot=slot)
