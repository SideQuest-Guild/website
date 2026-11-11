"""The Battle.net game data client (the ``wow`` package), one per app so its app token is fetched once and reused.

It uses the same Battle.net app as account linking (``WEB_BATTLENET_CLIENT_ID``/``SECRET``). Without them the client
is ``None`` and routes that need it answer 503. Tests pass a mock transport to ``create_app``.
"""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from litestar.datastructures import State  # noqa: TC002 - provide_game_data is a Litestar DI target
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE
from wow import AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from contextlib import AbstractAsyncContextManager

    from litestar import Litestar

    from sidequest_common.settings import WebSettings

GAME_DATA_STATE_KEY = "game_data"


def game_data_lifespan(
    web_settings: WebSettings, transport: httpx.AsyncBaseTransport | None = None
) -> Callable[[Litestar], AbstractAsyncContextManager[None]]:
    """Open the client when the app starts and close it when the app stops."""

    @asynccontextmanager
    async def lifespan(app: Litestar) -> AsyncIterator[None]:
        client_id, client_secret = web_settings.BATTLENET_CLIENT_ID, web_settings.BATTLENET_CLIENT_SECRET
        if client_id is None or client_secret is None:
            app.state[GAME_DATA_STATE_KEY] = None
            yield
            return
        http = httpx.AsyncClient(transport=transport) if transport is not None else None
        static_version = web_settings.BATTLENET_STATIC_VERSION
        async with AsyncClient(
            client_id, client_secret.get_secret_value(), http_client=http, static_version=static_version
        ) as client:
            app.state[GAME_DATA_STATE_KEY] = client
            try:
                yield
            finally:
                if http is not None:
                    await http.aclose()

    return lifespan


async def provide_game_data(state: State) -> AsyncClient:
    """The game data client, or 503 if Battle.net is not configured."""
    client = state.get(GAME_DATA_STATE_KEY)
    if client is None:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail="Battle.net is not configured")
    return client


async def provide_optional_game_data(state: State) -> AsyncClient | None:
    """The game data client, or ``None`` if Battle.net is not configured, for routes that only sometimes need it."""
    return state.get(GAME_DATA_STATE_KEY)
