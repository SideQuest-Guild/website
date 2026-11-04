"""DI providers for the stats domain."""

from litestar.di import NamedDependency  # noqa: TC002
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.domain.stats.services import StatsService
from sidequest_common.settings import WebSettings  # noqa: TC001 - a Litestar DI target, needs a real type


async def provide_stats_service(
    db_session: NamedDependency[AsyncSession], web_settings: NamedDependency[WebSettings]
) -> StatsService:
    """A ``StatsService`` bound to the request's session and web settings."""
    return StatsService(db_session, web_settings)
