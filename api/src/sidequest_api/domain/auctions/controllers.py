"""Auction price endpoints: public prices, a member's own price watches, and the bot's sync/alert/watch feed.

Public prices are edge-cached ten minutes, the same as character pages: a house updates about hourly, so a short
edge cache barely lags Battle.net while saving most requests a round trip.
"""

from typing import Annotated
from uuid import UUID

from litestar import Controller, delete, get, post
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.exceptions import HTTPException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter
from litestar.status_codes import HTTP_204_NO_CONTENT, HTTP_400_BAD_REQUEST
from wow import AsyncClient

from sidequest_api.domain.auctions.dependencies import (
    provide_auction_bot_member,
    provide_auctions_service,
    require_site_guild,
)
from sidequest_api.domain.auctions.services import AuctionsService
from sidequest_api.domain.items.dependencies import provide_items_service
from sidequest_api.domain.items.services import ItemsService
from sidequest_api.lib.game_data import provide_game_data
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_SIGNED_IN, SECURITY_SESSION, GuildIdPath
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import (
    MAX_AUCTION_WATCHES,
    MAX_PRICE_IDS,
    AuctionAlertSchema,
    AuctionPriceMap,
    AuctionSyncReport,
    AuctionWatch,
    AuctionWatchCreate,
    ItemAuctionPrice,
)
from sidequest_common.settings import WebSettings

# An auction house updates about hourly: ten minutes at the edge, then stale for an hour while one fetch refreshes it.
EDGE_PRICE_CACHE = ResponseHeader(name=EDGE_CACHE_HEADER, value="max-age=600, stale-while-revalidate=3600")
_NOT_SITE_GUILD = ResponseSpec(None, description="This guild_id is not the SideQuest server.")
_UNLINKED = ResponseSpec(
    None, description="This guild_id is not the SideQuest server, or that Discord user hasn't linked the site."
)


def _parse_ids(ids: str) -> list[int]:
    """Parse a comma-separated ``ids`` query string into 1..MAX_PRICE_IDS item IDs. 400 otherwise."""
    raw = [part.strip() for part in ids.split(",") if part.strip()]
    if not raw or len(raw) > MAX_PRICE_IDS:
        msg = f"ids must list 1 to {MAX_PRICE_IDS} item IDs"
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=msg)
    try:
        return [int(part) for part in raw]
    except ValueError as exc:
        msg = "ids must be a comma-separated list of integers"
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=msg) from exc


class AuctionPricesController(Controller):
    """``/api/auctions/prices``: public auction prices, from the guild's faction houses."""

    path = "/api/auctions/prices"
    tags = ["Auctions"]
    dependencies = {"auctions_service": Provide(provide_auctions_service)}

    @get(
        "/{item_id:int}",
        operation_id="GetAuctionPrice",
        response_headers=[EDGE_PRICE_CACHE],
        opt=SKIP_SESSION,
        summary="Get an item's auction price",
        description=(
            "Returns the item's current lowest unit price across every house of the guild's faction, each "
            "house's own price, and its 14-day trend. An item nobody lists still answers 200, with null prices "
            "and empty houses/trend."
        ),
        response_description="The item's auction price.",
    )
    async def get_price(
        self,
        item_id: Annotated[int, Parameter(description="The item's game ID.", gt=0)],
        auctions_service: NamedDependency[AuctionsService],
    ) -> ItemAuctionPrice:
        return await auctions_service.get_item_price(item_id)

    @get(
        "/",
        operation_id="GetAuctionPrices",
        response_headers=[EDGE_PRICE_CACHE],
        opt=SKIP_SESSION,
        summary="Get several items' auction prices",
        description=(
            f"Returns one price summary per requested item ID, in request order. Takes 1 to {MAX_PRICE_IDS} "
            "comma-separated IDs; more (or none) answers 400."
        ),
        response_description="One price summary per requested item.",
        responses={400: ResponseSpec(None, description=f"ids must list 1 to {MAX_PRICE_IDS} item IDs.")},
    )
    async def get_prices(
        self,
        ids: Annotated[str, Parameter(description="Comma-separated item IDs, such as `19019,15846`.")],
        auctions_service: NamedDependency[AuctionsService],
    ) -> AuctionPriceMap:
        return await auctions_service.get_price_map(_parse_ids(ids))


class AuctionWatchesController(Controller):
    """``/api/me/auction-watches``: the signed-in member's own price watches."""

    path = "/api/me/auction-watches"
    tags = ["Auctions"]
    security = SECURITY_SESSION
    dependencies = {
        "auctions_service": Provide(provide_auctions_service),
        "items_service": Provide(provide_items_service),
        "game_data": Provide(provide_game_data),
    }

    @get(
        "/",
        operation_id="ListMyAuctionWatches",
        summary="List my price watches",
        description="Returns the signed-in member's price watches, newest first, with each item's current price.",
        response_description="The member's price watches.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def list_watches(
        self,
        current_member: NamedDependency[Member],
        auctions_service: NamedDependency[AuctionsService],
        items_service: NamedDependency[ItemsService],
        game_data: NamedDependency[AsyncClient],
    ) -> list[AuctionWatch]:
        return await auctions_service.list_watches(current_member, items_service, game_data)

    @post(
        "/",
        operation_id="SaveMyAuctionWatch",
        summary="Add or update a price watch",
        description=(
            f"Adds an item to the signed-in member's price watches, or changes its threshold if it's already "
            f"there. A member may watch at most {MAX_AUCTION_WATCHES} items."
        ),
        response_description="The saved price watch.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            409: ResponseSpec(None, description=f"The member already watches {MAX_AUCTION_WATCHES} items."),
        },
    )
    async def save_watch(
        self,
        data: JSONBody[AuctionWatchCreate],
        current_member: NamedDependency[Member],
        auctions_service: NamedDependency[AuctionsService],
        items_service: NamedDependency[ItemsService],
        game_data: NamedDependency[AsyncClient],
    ) -> AuctionWatch:
        return await auctions_service.save_watch(current_member, data, items_service, game_data)

    @delete(
        "/{item_id:int}",
        operation_id="DeleteMyAuctionWatch",
        summary="Remove a price watch",
        description="Removes one of the signed-in member's own price watches.",
        response_description="The price watch was removed.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            404: ResponseSpec(None, description="The member has no watch for this item."),
        },
    )
    async def delete_watch(
        self,
        item_id: Annotated[int, Parameter(description="The item's game ID.")],
        current_member: NamedDependency[Member],
        auctions_service: NamedDependency[AuctionsService],
    ) -> None:
        await auctions_service.delete_watch(current_member, item_id)


class AuctionsSyncController(Controller):
    """``/auctions``: the bot's auction sync and alert queue, bot-key only."""

    path = "/auctions"
    tags = ["Auctions"]
    dependencies = {
        "auctions_service": Provide(provide_auctions_service),
        "items_service": Provide(provide_items_service),
        "game_data": Provide(provide_game_data),
    }

    @post(
        "/sync",
        operation_id="SyncAuctions",
        summary="Sync auction prices",
        description=(
            "Fetches every auction house of the guild's faction from Battle.net, rebuilds current prices and "
            "today's daily history, and queues price-watch alerts. Returns 404 for any guild_id other than the "
            "SideQuest server."
        ),
        response_description="What the sync fetched, priced and queued.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def sync(
        self,
        guild_id: GuildIdPath,
        web_settings: NamedDependency[WebSettings],
        auctions_service: NamedDependency[AuctionsService],
        game_data: NamedDependency[AsyncClient],
    ) -> AuctionSyncReport:
        require_site_guild(guild_id, web_settings)
        return await auctions_service.sync(game_data)

    @get(
        "/alerts/pending",
        operation_id="ListPendingAuctionAlerts",
        summary="List pending price alerts",
        description="Returns every price-watch alert not yet acked, oldest first. Called by the bot to DM members.",
        response_description="Pending price alerts.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def pending_alerts(
        self,
        guild_id: GuildIdPath,
        web_settings: NamedDependency[WebSettings],
        auctions_service: NamedDependency[AuctionsService],
        items_service: NamedDependency[ItemsService],
        game_data: NamedDependency[AsyncClient],
    ) -> list[AuctionAlertSchema]:
        require_site_guild(guild_id, web_settings)
        return await auctions_service.pending_alerts(items_service, game_data)

    @post(
        "/alerts/{alert_id:uuid}/sent",
        operation_id="AckAuctionAlert",
        status_code=HTTP_204_NO_CONTENT,
        summary="Ack a price alert",
        description="Marks a price alert as sent (DMed), so it drops off the pending queue.",
        response_description="The alert was acked.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server, or no such alert.")},
    )
    async def ack_alert(
        self,
        guild_id: GuildIdPath,
        alert_id: Annotated[UUID, Parameter(description="The alert's ID.")],
        web_settings: NamedDependency[WebSettings],
        auctions_service: NamedDependency[AuctionsService],
    ) -> None:
        require_site_guild(guild_id, web_settings)
        await auctions_service.mark_alert_sent(alert_id)


class AuctionBotWatchesController(Controller):
    """``/members/{user_id}/auction-watches``: a Discord user's price watches, bot-key only."""

    path = "/members/{user_id:int}/auction-watches"
    tags = ["Auctions"]
    dependencies = {
        "auctions_service": Provide(provide_auctions_service),
        "items_service": Provide(provide_items_service),
        "game_data": Provide(provide_game_data),
        "target_member": Provide(provide_auction_bot_member),
    }

    @get(
        "/",
        operation_id="ListMemberAuctionWatches",
        summary="List a member's price watches",
        description=(
            "Returns the linked member's price watches, newest first, the same shape as `/api/me/auction-watches`."
        ),
        response_description="The member's price watches.",
        responses={404: _UNLINKED},
    )
    async def list_watches(
        self,
        target_member: NamedDependency[Member],
        auctions_service: NamedDependency[AuctionsService],
        items_service: NamedDependency[ItemsService],
        game_data: NamedDependency[AsyncClient],
    ) -> list[AuctionWatch]:
        return await auctions_service.list_watches(target_member, items_service, game_data)

    @post(
        "/",
        operation_id="SaveMemberAuctionWatch",
        summary="Add or update a member's price watch",
        description="Same as `POST /api/me/auction-watches`, for the member linked to this Discord user.",
        response_description="The saved price watch.",
        responses={
            404: _UNLINKED,
            409: ResponseSpec(None, description=f"The member already watches {MAX_AUCTION_WATCHES} items."),
        },
    )
    async def save_watch(
        self,
        data: JSONBody[AuctionWatchCreate],
        target_member: NamedDependency[Member],
        auctions_service: NamedDependency[AuctionsService],
        items_service: NamedDependency[ItemsService],
        game_data: NamedDependency[AsyncClient],
    ) -> AuctionWatch:
        return await auctions_service.save_watch(target_member, data, items_service, game_data)

    @delete(
        "/{item_id:int}",
        operation_id="DeleteMemberAuctionWatch",
        summary="Remove a member's price watch",
        description="Same as `DELETE /api/me/auction-watches/{item_id}`, for the member linked to this Discord user.",
        response_description="The price watch was removed.",
        responses={404: ResponseSpec(None, description="No site guild, no linked account, or no watch for this item.")},
    )
    async def delete_watch(
        self,
        item_id: Annotated[int, Parameter(description="The item's game ID.")],
        target_member: NamedDependency[Member],
        auctions_service: NamedDependency[AuctionsService],
    ) -> None:
        await auctions_service.delete_watch(target_member, item_id)
