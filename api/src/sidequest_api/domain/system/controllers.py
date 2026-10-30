"""Health endpoints for container orchestration (no auth)."""

from litestar import Controller, get
from litestar.di import NamedDependency
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class HealthController(Controller):
    """``/health`` checks the database; ``/health/live`` only checks the process."""

    path = "/health"
    tags = ["System"]

    @get(
        "/",
        operation_id="HealthCheck",
        summary="Check process and database health",
        description="Checks that the process is running and the database is reachable.",
        response_description="The process and database are healthy.",
    )
    async def health(self, db_session: NamedDependency[AsyncSession]) -> dict[str, str]:
        await db_session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    @get(
        "/live",
        operation_id="LivenessCheck",
        summary="Check process liveness",
        description="Checks that the process is running.",
        response_description="The process is running.",
    )
    async def live(self) -> dict[str, str]:
        return {"status": "ok"}
