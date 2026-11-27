"""DI providers for the sims domain.

``wowsims_dir`` comes from ``create_app``; ``game_data`` and ``characters_service`` are shared with the characters
domain.
"""

from litestar.di import NamedDependency  # noqa: TC002 - provide_sims_service is a Litestar DI target
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002 - provide_sims_service is a Litestar DI target

from sidequest_api.domain.sims.services import SimsService


async def provide_sims_service(db_session: NamedDependency[AsyncSession]) -> SimsService:
    """A ``SimsService`` bound to the request's session."""
    return SimsService(db_session)
