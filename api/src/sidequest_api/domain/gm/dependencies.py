"""DI providers for the GM console domain."""

from litestar.di import NamedDependency  # noqa: TC002
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.domain.gm.services import GmService
from sidequest_common.settings import WebSettings  # noqa: TC001 - a Litestar DI target, needs a real type


async def provide_gm_service(
    db_session: NamedDependency[AsyncSession], web_settings: NamedDependency[WebSettings]
) -> GmService:
    """A ``GmService`` bound to the request's session and web settings."""
    return GmService(db_session, web_settings)
