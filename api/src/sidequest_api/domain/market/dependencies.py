"""DI providers for the market domain, and the feed's key check."""

import hmac
from typing import TYPE_CHECKING

from litestar.connection import ASGIConnection  # noqa: TC002 - a Litestar DI target, needs a real type
from litestar.di import NamedDependency  # noqa: TC002 - a Litestar DI target, needs a real type
from litestar.exceptions import HTTPException, NotAuthorizedException
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002 - a Litestar DI target, needs a real type

from sidequest_api.domain.market.services import MarketService

if TYPE_CHECKING:
    from sidequest_common.settings import WebSettings

MARKET_KEY_HEADER = "X-Market-Key"


async def provide_market_service(db_session: NamedDependency[AsyncSession]) -> MarketService:
    """A ``MarketService`` bound to the request's session."""
    return MarketService(db_session)


def require_market_feed_key(connection: ASGIConnection, web_settings: WebSettings) -> None:
    """503 while the site has no feed key configured; 401 unless ``X-Market-Key`` matches it."""
    expected = web_settings.MARKET_FEED_KEY
    if expected is None:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail="The market feed is not set up")
    supplied = connection.headers.get(MARKET_KEY_HEADER, "")
    if not hmac.compare_digest(supplied.encode(), expected.get_secret_value().encode()):
        msg = "Missing or invalid market feed key"
        raise NotAuthorizedException(msg)
