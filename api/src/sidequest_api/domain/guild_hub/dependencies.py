"""DI providers for the guild hub domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.di import NamedDependency  # noqa: TC002 - Litestar DI target, needs a real type

from sidequest_api.domain.guild_hub.services import GuildHubService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def provide_guild_hub_service(db_session: NamedDependency[AsyncSession]) -> GuildHubService:
    """A ``GuildHubService`` bound to the request's session."""
    return GuildHubService(db_session)
