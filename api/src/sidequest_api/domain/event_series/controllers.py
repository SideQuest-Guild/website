"""Repeating guild event series endpoints: public read, officer manage.

Officer gating is dependency-based (``current_officer``, registered app-wide in ``create_app``): declaring the
parameter resolves it, raising 401/403 before the handler body runs.
"""

from typing import Annotated
from uuid import UUID

from litestar import Controller, delete, get, patch, post
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.event_series.dependencies import provide_event_series_service
from sidequest_api.domain.event_series.services import EventSeriesService
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import EventSeriesCreate, EventSeriesSummary, EventSeriesUpdate

_SERIES_ID = Annotated[UUID, Parameter(description="The event series' ID.")]


class EventSeriesController(Controller):
    """``/api/event-series``."""

    path = "/api/event-series"
    dependencies = {"event_series_service": Provide(provide_event_series_service)}

    @get(
        "/",
        operation_id="ListEventSeries",
        tags=["Event series"],
        summary="List event series",
        description="Returns every active repeating series, with each one's soonest future occurrence.",
        response_description="The active event series.",
    )
    async def list_series(self, event_series_service: NamedDependency[EventSeriesService]) -> list[EventSeriesSummary]:
        return await event_series_service.list_active()

    @post(
        "/",
        operation_id="CreateEventSeries",
        status_code=201,
        tags=["Event series management"],
        security=SECURITY_SESSION,
        summary="Create an event series",
        description=(
            "Creates a repeating series and materializes its occurrences immediately. An officer must be signed in."
        ),
        response_description="The newly created series.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def create_series(
        self,
        data: JSONBody[EventSeriesCreate],
        event_series_service: NamedDependency[EventSeriesService],
        current_officer: NamedDependency[Member],
    ) -> EventSeriesSummary:
        series = await event_series_service.create_series(data)
        await record_officer_audit(
            event_series_service.repository.session,
            actor=current_officer,
            action="series.create",
            subject_type="series",
            subject_id=str(series.id),
            summary=f'Created series "{series.title}"',
        )
        return series

    @patch(
        "/{series_id:uuid}",
        operation_id="UpdateEventSeries",
        tags=["Event series management"],
        security=SECURITY_SESSION,
        summary="Edit an event series",
        description=(
            "Edits a series' content or schedule. An officer must be signed in. Retimes or retires affected "
            "future occurrences, then materializes new ones."
        ),
        response_description="The updated series.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="No event series with that ID."),
            400: ResponseSpec(None, description="The resulting end date is before the start date."),
        },
    )
    async def update_series(
        self,
        series_id: _SERIES_ID,
        data: JSONBody[EventSeriesUpdate],
        event_series_service: NamedDependency[EventSeriesService],
        current_officer: NamedDependency[Member],
    ) -> EventSeriesSummary:
        series = await event_series_service.update_series(series_id, data)
        await record_officer_audit(
            event_series_service.repository.session,
            actor=current_officer,
            action="series.update",
            subject_type="series",
            subject_id=str(series.id),
            summary=f'Updated series "{series.title}"',
        )
        return series

    @delete(
        "/{series_id:uuid}",
        operation_id="DeleteEventSeries",
        tags=["Event series management"],
        security=SECURITY_SESSION,
        summary="End an event series",
        description=(
            "Ends a series. An officer must be signed in. Keeps past occurrences, deletes or cancels future ones, "
            "then deletes the series."
        ),
        response_description="The series was ended.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="No event series with that ID."),
        },
    )
    async def delete_series(
        self,
        series_id: _SERIES_ID,
        event_series_service: NamedDependency[EventSeriesService],
        current_officer: NamedDependency[Member],
    ) -> None:
        series = await event_series_service.get_series_or_404(series_id)
        await event_series_service.end_series(series_id)
        await record_officer_audit(
            event_series_service.repository.session,
            actor=current_officer,
            action="series.delete",
            subject_type="series",
            subject_id=str(series_id),
            summary=f'Ended series "{series.title}"',
        )
