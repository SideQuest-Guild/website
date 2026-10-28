"""Repeating guild event series endpoints: public read, officer manage.

Officer gating is dependency-based (``current_officer``, registered app-wide in ``create_app``): declaring the
parameter resolves it, raising 401/403 before the handler body runs.
"""

from uuid import UUID

from litestar import Controller, delete, get, patch, post
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, JSONBody

from sidequest_api.domain.event_series.dependencies import provide_event_series_service
from sidequest_api.domain.event_series.services import EventSeriesService
from sidequest_common.models import Member
from sidequest_common.schemas import EventSeriesCreate, EventSeriesSummary, EventSeriesUpdate


class EventSeriesController(Controller):
    """``/api/event-series``."""

    path = "/api/event-series"
    tags = ["Event Series"]
    dependencies = {"event_series_service": Provide(provide_event_series_service)}

    @get("/", operation_id="ListEventSeries")
    async def list_series(self, event_series_service: NamedDependency[EventSeriesService]) -> list[EventSeriesSummary]:
        """Every active repeating series, with each one's soonest future occurrence."""
        return await event_series_service.list_active()

    @post("/", operation_id="CreateEventSeries", status_code=201)
    async def create_series(
        self,
        data: JSONBody[EventSeriesCreate],
        event_series_service: NamedDependency[EventSeriesService],
        current_officer: NamedDependency[Member],
    ) -> EventSeriesSummary:
        """Create a repeating series (officer); materializes its occurrences immediately."""
        del current_officer
        return await event_series_service.create_series(data)

    @patch("/{series_id:uuid}", operation_id="UpdateEventSeries")
    async def update_series(
        self,
        series_id: FromPath[UUID],
        data: JSONBody[EventSeriesUpdate],
        event_series_service: NamedDependency[EventSeriesService],
        current_officer: NamedDependency[Member],
    ) -> EventSeriesSummary:
        """Edit a series' content or schedule (officer); retimes/retires affected occurrences, then materializes."""
        del current_officer
        return await event_series_service.update_series(series_id, data)

    @delete("/{series_id:uuid}", operation_id="DeleteEventSeries")
    async def delete_series(
        self,
        series_id: FromPath[UUID],
        event_series_service: NamedDependency[EventSeriesService],
        current_officer: NamedDependency[Member],
    ) -> None:
        """End a series (officer): keeps past occurrences, deletes/cancels future ones, deletes the series row."""
        del current_officer
        await event_series_service.end_series(series_id)
