"""Market report endpoints: the price feed in, the report out to members and to the bot.

The report is members only: it is a guild perk, and it isn't edge-cached because a member's session decides access.
"""

from typing import Annotated

from litestar import Controller, Request, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.auctions.dependencies import require_site_guild
from sidequest_api.domain.market.dependencies import provide_market_service, require_market_feed_key
from sidequest_api.domain.market.services import MarketService
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_SIGNED_IN, SECURITY_MARKET_FEED, SECURITY_SESSION, GuildIdPath
from sidequest_common.models import Member
from sidequest_common.schemas import MarketFeed, MarketFeedReceipt, MarketReport, MarketReportKind
from sidequest_common.settings import WebSettings

FEED_MAX_BYTES = 32 * 1024 * 1024
"""A whole house's feed is a few megabytes; Litestar's default 10 MB cap leaves too little room."""
NO_DATA = "No market data yet"
_NO_DATA = ResponseSpec(None, description="No price feed has arrived yet.")
_KIND = Parameter(description="`daily` compares with the week before; `weekly` compares with last week.")


async def _report(market_service: MarketService, kind: MarketReportKind) -> MarketReport:
    report = await market_service.report(kind)
    if report is None:
        raise NotFoundException(NO_DATA)
    return report


class MarketFeedController(Controller):
    """``/api/market/feed``: the price feed for the guild's auction house, with its own key."""

    path = "/api/market/feed"
    tags = ["Market report"]
    security = SECURITY_MARKET_FEED
    dependencies = {"market_service": Provide(provide_market_service)}

    @post(
        "/",
        operation_id="PostMarketFeed",
        request_max_body_size=FEED_MAX_BYTES,
        summary="Send the market feed",
        description=(
            "Replaces one auction house's item numbers and recipes. Needs the `X-Market-Key` header. Answers 503 "
            "while the site has no feed key set."
        ),
        response_description="How many items and recipes were stored.",
        responses={
            401: ResponseSpec(None, description="The `X-Market-Key` header is missing or wrong."),
            503: ResponseSpec(None, description="The site has no market feed key set."),
        },
    )
    async def post_feed(
        self,
        request: Request,
        data: JSONBody[MarketFeed],
        web_settings: NamedDependency[WebSettings],
        market_service: NamedDependency[MarketService],
    ) -> MarketFeedReceipt:
        require_market_feed_key(request, web_settings)
        return await market_service.store_feed(data)


class MarketReportController(Controller):
    """``/api/market/report``: the market report, for signed-in guild members."""

    path = "/api/market/report"
    tags = ["Market report"]
    security = SECURITY_SESSION
    dependencies = {"market_service": Provide(provide_market_service)}

    @get(
        "/",
        operation_id="GetMarketReport",
        summary="Get the market report",
        description=(
            "What to gather and craft for gold on the guild's auction house: the best materials per gathering "
            "profession with where to find them, the best crafts per crafting profession with their material "
            "costs, and the biggest price moves. Answers 404 before the first price feed."
        ),
        response_description="The market report.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER, 404: _NO_DATA},
    )
    async def get_report(
        self,
        current_member: NamedDependency[Member],  # noqa: ARG002 - the member guard: signed in and in the guild
        market_service: NamedDependency[MarketService],
        kind: Annotated[MarketReportKind, _KIND] = "daily",
    ) -> MarketReport:
        return await _report(market_service, kind)


class MarketReportBotController(Controller):
    """``/market-report``: the market report for the bot's daily post, bot-key only."""

    path = "/market-report"
    tags = ["Market report"]
    dependencies = {"market_service": Provide(provide_market_service)}

    @get(
        "/",
        operation_id="GetBotMarketReport",
        summary="Get the market report for the bot",
        description=(
            "The same report members see, for the bot's daily post. Answers 404 before the first price feed, or "
            "for any guild_id other than the SideQuest server."
        ),
        response_description="The market report.",
        responses={404: ResponseSpec(None, description="Not the SideQuest server, or no price feed yet.")},
    )
    async def get_report(
        self,
        guild_id: GuildIdPath,
        web_settings: NamedDependency[WebSettings],
        market_service: NamedDependency[MarketService],
        kind: Annotated[MarketReportKind, _KIND] = "daily",
    ) -> MarketReport:
        require_site_guild(guild_id, web_settings)
        return await _report(market_service, kind)
