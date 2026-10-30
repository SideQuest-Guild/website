"""The MCP protocol endpoint: ``/api/mcp``, mounted under ``/api`` so Cloudflare and the service worker never cache it.

Uses the official ``mcp`` SDK's stateless, JSON-response streamable-HTTP transport (no long-lived SSE connections
through Cloudflare). The endpoint is a raw ASGI mount rather than a Litestar controller because the SDK's tool
functions aren't Litestar route handlers; auth and per-request context (``domain.mcp.context``) are wired in by
hand around the SDK's app.
"""

from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from sidequest_api.domain.mcp.auth import McpAuthError, authenticate
from sidequest_api.domain.mcp.context import McpRequestContext, current_context
from sidequest_api.domain.mcp.tools import register_tools
from sidequest_api.lib.discord import DISCORD_API_BASE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from types import TracebackType

    from litestar.types import HTTPResponseBodyEvent, HTTPResponseStartEvent, Receive, Scope, Send
    from sqlalchemy.ext.asyncio import AsyncSession

    from sidequest_common.settings import WebSettings

MCP_MOUNT_PATH = "/api/mcp"


async def _send_error(send: Send, status_code: int, message: str) -> None:
    start: HTTPResponseStartEvent = {
        "type": "http.response.start",
        "status": status_code,
        "headers": [(b"content-type", b"application/json")],
    }
    body: HTTPResponseBodyEvent = {
        "type": "http.response.body",
        "body": json.dumps({"error": message}).encode(),
        "more_body": False,
    }
    await send(start)
    await send(body)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def build_mcp_mount(
    *,
    web_settings: WebSettings,
    session_maker: Callable[[], AsyncSession],
    bot_token: str | None,
    guild_id: int,
    discord_transport: httpx.BaseTransport | None = None,
) -> tuple[Callable[[Scope, Receive, Send], Awaitable[None]], AbstractAsyncContextManager[None]]:
    """Build the ``/api/mcp`` ASGI handler and the lifespan context manager that runs its session manager.

    ``session_maker`` opens the handler's own DB sessions (it can't use Litestar's per-request dependency
    injection, since a mounted ASGI handler only receives ``scope``/``receive``/``send``).
    """
    mcp = MCPServer("SideQuest Guild", instructions="Officer tools for the SideQuest Guild Discord server and site.")
    register_tools(mcp)
    inner_app = mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    class _SessionManagerLifespan(AbstractAsyncContextManager[None]):
        async def __aenter__(self) -> None:
            self._cm = mcp.session_manager.run()
            await self._cm.__aenter__()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            await self._cm.__aexit__(exc_type, exc, traceback)

    async_transport = discord_transport if isinstance(discord_transport, httpx.AsyncBaseTransport) else None

    async def handler(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # MCP's streamable HTTP transport never uses WebSockets
            return
        authorization = _header(scope, b"authorization")
        async with session_maker() as session:
            try:
                actor = await authenticate(session, web_settings, authorization)
            except McpAuthError as error:
                await _send_error(send, error.status_code, str(error))
                return
            async with httpx.AsyncClient(
                base_url=DISCORD_API_BASE, timeout=10.0, transport=async_transport
            ) as discord_client:
                token = current_context.set(
                    McpRequestContext(
                        session=session,
                        actor=actor,
                        web_settings=web_settings,
                        discord_client=discord_client,
                        bot_token=bot_token,
                        guild_id=guild_id,
                    )
                )
                try:
                    await inner_app(scope, receive, send)
                finally:
                    current_context.reset(token)

    return handler, _SessionManagerLifespan()
