"""DI providers for the MCP token-management domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.di import NamedDependency  # noqa: TC002 - Litestar DI target, needs a real type

from sidequest_api.domain.mcp.services import McpTokenService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def provide_mcp_token_service(db_session: NamedDependency[AsyncSession]) -> McpTokenService:
    """An ``McpTokenService`` bound to the request's session."""
    return McpTokenService(db_session)
