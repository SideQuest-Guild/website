"""DI providers for the Hall of Heroes domain."""

from litestar.di import NamedDependency  # noqa: TC002
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.domain.heroes.services import HeroesService
from sidequest_common.settings import WebSettings  # noqa: TC001 - a Litestar DI target, needs a real type


async def provide_heroes_service(
    db_session: NamedDependency[AsyncSession], web_settings: NamedDependency[WebSettings]
) -> HeroesService:
    """A ``HeroesService`` bound to the request's session and web settings."""
    return HeroesService(db_session, web_settings)
