"""DI providers for the PvP domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.di import NamedDependency  # noqa: TC002 - Litestar DI target, needs a real type

from sidequest_api.domain.pvp.services import PvpService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def provide_pvp_service(db_session: NamedDependency[AsyncSession]) -> PvpService:
    """A ``PvpService`` bound to the request's session."""
    return PvpService(db_session)
