"""DI providers for the group voice (LFG) domain."""

from litestar.di import NamedDependency  # noqa: TC002
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.domain.groups.services import GroupsService


async def provide_groups_service(db_session: NamedDependency[AsyncSession]) -> GroupsService:
    """A ``GroupsService`` bound to the request's session."""
    return GroupsService(db_session)
