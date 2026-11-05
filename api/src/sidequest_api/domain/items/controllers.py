"""Item endpoints: public item lookup and item search from Battle.net's Item API, and wishlists.

``GET /api/items/{item_id}`` is the same for every visitor and has no query string, so Cloudflare may keep it at the
edge. Search answers differ by query string, which Cloudflare's cache rule ignores, so search is never edge-cached;
the API caches each search for ten minutes instead. A member keeps their own wishlist at ``/api/me/wishlist``;
officers see who wants an item at ``/api/items/{item_id}/wishers``.
"""

from typing import Annotated

from litestar import Controller, delete, get, put
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter
from wow import AsyncClient

from sidequest_api.domain.items.dependencies import provide_items_service, provide_wishlist_service
from sidequest_api.domain.items.services import ItemsService, search_items
from sidequest_api.domain.items.wishlist import WishlistService
from sidequest_api.lib.game_data import provide_game_data
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import (
    ITEM_SEARCH_MIN_LENGTH,
    MAX_ITEM_WISHES,
    ItemQuality,
    ItemSchema,
    ItemSearchPage,
    ItemWisher,
    ItemWishSchema,
    ItemWishUpdate,
)

_ITEM_ID = Annotated[int, Parameter(description="The item's game ID.", gt=0)]

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


class MyWishlistController(Controller):
    """``/api/me/wishlist``: the signed-in member's own wishlist."""

    path = "/api/me/wishlist"
    tags = ["My wishlist"]
    security = SECURITY_SESSION
    dependencies = {
        "wishlist_service": Provide(provide_wishlist_service),
        "items_service": Provide(provide_items_service),
        "game_data": Provide(provide_game_data),
    }

    @get(
        "/",
        operation_id="ListMyWishlist",
        summary="List my wishlist",
        description="Returns the items on the signed-in member's wishlist, newest first.",
        response_description="The member's wishlist.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def list_wishlist(
        self, current_member: NamedDependency[Member], wishlist_service: NamedDependency[WishlistService]
    ) -> list[ItemWishSchema]:
        return await wishlist_service.list_for(current_member)

    @put(
        "/{item_id:int}",
        operation_id="SaveMyWish",
        summary="Add an item to my wishlist",
        description=(
            f"Adds the item to the signed-in member's wishlist, or changes its note if it's already there. A "
            f"wishlist holds {MAX_ITEM_WISHES} items. Officers see who wants an item; the loot rules don't change."
        ),
        response_description="The member's whole wishlist after the change.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            404: ResponseSpec(None, description="Battle.net has no item with this ID."),
            409: ResponseSpec(None, description=f"The wishlist already holds {MAX_ITEM_WISHES} items."),
        },
    )
    async def save_wish(
        self,
        *,
        item_id: _ITEM_ID,
        data: JSONBody[ItemWishUpdate],
        current_member: NamedDependency[Member],
        wishlist_service: NamedDependency[WishlistService],
        items_service: NamedDependency[ItemsService],
        game_data: NamedDependency[AsyncClient],
    ) -> list[ItemWishSchema]:
        return await wishlist_service.save(
            current_member, item_id, data.note, items_service=items_service, game_data=game_data
        )

    @delete(
        "/{item_id:int}",
        operation_id="RemoveMyWish",
        summary="Take an item off my wishlist",
        description="Removes the item from the signed-in member's wishlist. Removing an item that isn't there is fine.",
        response_description="The item is off the wishlist.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def remove_wish(
        self,
        item_id: _ITEM_ID,
        current_member: NamedDependency[Member],
        wishlist_service: NamedDependency[WishlistService],
    ) -> None:
        await wishlist_service.remove(current_member, item_id)


class ItemWishersController(Controller):
    """``/api/items/{item_id}/wishers``: who wants an item, for officers deciding loot."""

    path = "/api/items"
    tags = ["Wishlists"]
    security = SECURITY_SESSION
    dependencies = {"wishlist_service": Provide(provide_wishlist_service)}

    @get(
        "/{item_id:int}/wishers",
        operation_id="ListItemWishers",
        summary="List who wants an item",
        description=(
            "Returns every member with the item on their wishlist, with their note and loot points (EP, GP and "
            "priority, after decay), highest priority first. An officer must be signed in."
        ),
        response_description="The members who want the item.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def list_wishers(
        self,
        item_id: _ITEM_ID,
        current_officer: NamedDependency[Member],  # noqa: ARG002 - the dependency is the officer check
        wishlist_service: NamedDependency[WishlistService],
    ) -> list[ItemWisher]:
        return await wishlist_service.wishers(item_id)
