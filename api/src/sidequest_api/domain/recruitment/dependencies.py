"""DI providers for the recruitment domain."""

from litestar.di import NamedDependency  # noqa: TC002
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.domain.recruitment.services import RecruitmentService


async def provide_recruitment_service(db_session: NamedDependency[AsyncSession]) -> RecruitmentService:
    """A ``RecruitmentService`` bound to the request's session."""
    return RecruitmentService(db_session)
