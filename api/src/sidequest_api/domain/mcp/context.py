"""Per-MCP-request context.

The MCP protocol endpoint is a raw ASGI mount wrapping the ``mcp`` SDK's streamable-HTTP app, not a set of
Litestar route handlers, so tool functions can't receive Litestar-style dependency injection. Instead, the ASGI
handler in ``server.py`` authenticates the request, builds one ``McpRequestContext``, and stores it in a
``contextvars.ContextVar`` for the duration of the call; tool functions read it back with ``get_context()``.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

from mcp.server.mcpserver.exceptions import ToolError

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from sidequest_common.models import Member
    from sidequest_common.settings import WebSettings


class McpRequestContext:
    """Everything a tool function needs for the request it's running inside."""

    __slots__ = ("actor", "bot_token", "discord_client", "guild_id", "session", "web_settings")

    def __init__(
        self,
        *,
        session: AsyncSession,
        actor: Member,
        web_settings: WebSettings,
        discord_client: httpx.AsyncClient,
        bot_token: str | None,
        guild_id: int,
    ) -> None:
        self.session = session
        self.actor = actor
        self.web_settings = web_settings
        self.discord_client = discord_client
        self.bot_token = bot_token
        self.guild_id = guild_id


current_context: ContextVar[McpRequestContext] = ContextVar("mcp_request_context")


def get_context() -> McpRequestContext:
    """The current request's context. Raises ``LookupError`` if called outside of an authenticated MCP request."""
    return current_context.get()


def require_bot_token(ctx: McpRequestContext) -> str:
    """``ctx.bot_token``, or a clear error if Discord isn't configured (``DISCORD_TOKEN`` unset).

    Discord tools fail with this message instead of crashing; the rest of the site keeps working either way.
    """
    if ctx.bot_token is None:
        msg = "Discord isn't configured on this server (DISCORD_TOKEN is unset), so this tool is unavailable."
        raise ToolError(msg)
    return ctx.bot_token
