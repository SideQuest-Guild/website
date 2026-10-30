"""DI providers for the attendance domain."""

from litestar.di import NamedDependency  # noqa: TC002
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.domain.attendance.services import AttendanceService


async def provide_attendance_service(db_session: NamedDependency[AsyncSession]) -> AttendanceService:
    """An ``AttendanceService`` bound to the request's session."""
    return AttendanceService(db_session)
