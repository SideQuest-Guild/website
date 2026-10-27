"""Health endpoints for container orchestration (no auth)."""

from litestar import Controller, get
from litestar.di import NamedDependency
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class HealthController(Controller):
    """``/health`` checks the database; ``/health/live`` only checks the process."""

    path = "/health"
    tags = ["System"]

    @get("/", operation_id="HealthCheck")
    async def health(self, db_session: NamedDependency[AsyncSession]) -> dict[str, str]:
        """Process and database are up."""
        await db_session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    @get("/live", operation_id="LivenessCheck")
    async def live(self) -> dict[str, str]:
        """Process is up."""
        return {"status": "ok"}
