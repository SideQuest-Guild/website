"""Shared-secret auth for bot -> API calls.

``create_app`` attaches this guard to the bot's guild router (``/api/guilds/{guild_id}``), which then requires
``X-API-Key: <API_KEY>``. Website and other public routes are mounted outside that router.
"""

import hmac
from typing import TYPE_CHECKING

from litestar.exceptions import NotAuthorizedException

if TYPE_CHECKING:
    from collections.abc import Callable

    from litestar.connection import ASGIConnection
    from litestar.handlers.base import BaseRouteHandler

API_KEY_HEADER = "X-API-Key"


def api_key_guard(expected_key: str) -> Callable[[ASGIConnection, BaseRouteHandler], None]:
    """Guard that rejects requests whose ``X-API-Key`` doesn't match ``expected_key``."""
    expected = expected_key.encode()

    def guard(connection: ASGIConnection, _handler: BaseRouteHandler) -> None:
        supplied = connection.headers.get(API_KEY_HEADER, "")
        if not hmac.compare_digest(supplied.encode(), expected):
            msg = "Missing or invalid API key"
            raise NotAuthorizedException(msg)

    return guard
