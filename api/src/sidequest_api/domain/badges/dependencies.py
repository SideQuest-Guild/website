"""DI providers for the Hall of Heroes badges domain."""

from litestar.di import NamedDependency  # noqa: TC002
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.domain.badges.services import BadgeService


async def provide_badge_service(db_session: NamedDependency[AsyncSession]) -> BadgeService:
    """A ``BadgeService`` bound to the request's session."""
    return BadgeService(db_session)
