"""Guild event and signup endpoints: public read, member signup, officer manage (including the raid chart).

Member/officer gating is dependency-based (``current_member``/``current_officer``, registered app-wide in
``create_app``): declaring the parameter resolves it, raising 401/403 before the handler body runs.
"""

from typing import Annotated, Literal
from uuid import UUID

from litestar import Controller, delete, get, patch, post, put
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.events.dependencies import provide_event_signups_service, provide_events_service
from sidequest_api.domain.events.services import EventSignupsService, EventsService
from sidequest_api.lib.member_auth import provide_optional_member
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import (
    ChartUpdate,
    EventCreate,
    EventDetail,
    EventKind,
    EventSummary,
    EventUpdate,
    Signup,
    SignupUpsert,
)

_EVENT_ID = Annotated[UUID, Parameter(description="The event's ID.")]


class EventsController(Controller):
    """``/api/events``."""

    path = "/api/events"
    dependencies = {
        "events_service": Provide(provide_events_service),
        "event_signups_service": Provide(provide_event_signups_service),
        "optional_member": Provide(provide_optional_member),
    }

    @get(
        "/",
        operation_id="ListEvents",
        tags=["Events"],
        summary="List events",
        description=(
            "Returns events for the given window. Anonymous visitors without a session or bot API key get only "
            "the headline fields; the `counts` field is null."
        ),
        response_description="The matching events, newest first.",
    )
    async def list_events(
        self,
        events_service: NamedDependency[EventsService],
        full_access: NamedDependency[bool],
        when: Annotated[
            Literal["upcoming", "past"], Parameter(description="Which window of events to list.")
        ] = "upcoming",
        kind: Annotated[EventKind | None, Parameter(description="Restrict the list to one event kind.")] = None,
    ) -> list[EventSummary]:
        return await events_service.list_summaries(when, kind, full_access=full_access)

    @get(
        "/{event_id:uuid}",
        operation_id="GetEvent",
        tags=["Events"],
        summary="Get an event",
        description=(
            "Returns an event with its full roster. Anonymous visitors without a session or bot API key get only "
            "the headline fields; `notes`, `counts`, and `discord_interest` are null, and `signups`/`my_signup` "
            "are empty."
        ),
        response_description="The event. `my_signup` is the caller's own signup, if any.",
        responses={404: ResponseSpec(None, description="No event with that ID.")},
    )
    async def get_event(
        self,
        event_id: _EVENT_ID,
        events_service: NamedDependency[EventsService],
        optional_member: NamedDependency[Member | None],
        full_access: NamedDependency[bool],
    ) -> EventDetail:
        return await events_service.get_detail(event_id, viewer=optional_member, full_access=full_access)

    @put(
        "/{event_id:uuid}/signup",
        operation_id="UpsertSignup",
        tags=["Event signups"],
        security=SECURITY_SESSION,
        summary="Create or update your signup",
        description=(
            "Creates or replaces the signed-in member's signup for an event. Returns 404 for an unknown event "
            "and 409 if the event is not open for signups."
        ),
        response_description="The member's signup.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            404: ResponseSpec(None, description="No event with that ID."),
            409: ResponseSpec(None, description="The event is not open for signups, or the signup already exists."),
        },
    )
    async def upsert_signup(
        self,
        event_id: _EVENT_ID,
        data: JSONBody[SignupUpsert],
        event_signups_service: NamedDependency[EventSignupsService],
        current_member: NamedDependency[Member],
    ) -> Signup:
        return await event_signups_service.upsert_signup(event_id, current_member, data)

    @delete(
        "/{event_id:uuid}/signup",
        operation_id="DeleteSignup",
        tags=["Event signups"],
        security=SECURITY_SESSION,
        summary="Remove your signup",
        description="Removes the signed-in member's signup for an event, if any.",
        response_description="The signup was removed.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def delete_signup(
        self,
        event_id: _EVENT_ID,
        event_signups_service: NamedDependency[EventSignupsService],
        current_member: NamedDependency[Member],
    ) -> None:
        await event_signups_service.delete_for_member(event_id, current_member)

    @post(
        "/",
        operation_id="CreateEvent",
        status_code=201,
        tags=["Event scheduling"],
        security=SECURITY_SESSION,
        summary="Schedule an event",
        description="Creates a new guild event. An officer must be signed in.",
        response_description="The newly created event.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def create_event(
        self,
        data: JSONBody[EventCreate],
        events_service: NamedDependency[EventsService],
        current_officer: NamedDependency[Member],
    ) -> EventDetail:
        event = await events_service.create_event(data)
        await record_officer_audit(
            events_service.repository.session,
            actor=current_officer,
            action="event.create",
            subject_type="event",
            subject_id=str(event.id),
            summary=f'Created {event.kind} "{event.title}" for {event.starts_at:%b %-d}',
        )
        return await events_service.get_detail(event.id, viewer=None, full_access=True)

    @patch(
        "/{event_id:uuid}",
        operation_id="UpdateEvent",
        tags=["Event scheduling"],
        security=SECURITY_SESSION,
        summary="Edit an event",
        description=(
            "Edits an event, including its kind and status. An officer must be signed in. Editing an event that "
            "belongs to a series detaches it, so later series-wide edits stop touching it."
        ),
        response_description="The updated event.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="No event with that ID."),
            400: ResponseSpec(None, description="The resulting end time is not after the start time."),
        },
    )
    async def update_event(
        self,
        event_id: _EVENT_ID,
        data: JSONBody[EventUpdate],
        events_service: NamedDependency[EventsService],
        current_officer: NamedDependency[Member],
    ) -> EventDetail:
        event = await events_service.update_event(event_id, data)
        await record_officer_audit(
            events_service.repository.session,
            actor=current_officer,
            action="event.update",
            subject_type="event",
            subject_id=str(event.id),
            summary=f'Updated event "{event.title}"',
        )
        return await events_service.get_detail(event.id, viewer=None, full_access=True)

    @delete(
        "/{event_id:uuid}",
        operation_id="DeleteEvent",
        tags=["Event scheduling"],
        security=SECURITY_SESSION,
        summary="Delete an event",
        description="Deletes an event and its signups. An officer must be signed in.",
        response_description="The event was deleted.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="No event with that ID."),
        },
    )
    async def delete_event(
        self,
        event_id: _EVENT_ID,
        events_service: NamedDependency[EventsService],
        current_officer: NamedDependency[Member],
    ) -> None:
        event = await events_service.get_event_or_404(event_id)
        await events_service.delete_event(event_id)
        await record_officer_audit(
            events_service.repository.session,
            actor=current_officer,
            action="event.delete",
            subject_type="event",
            subject_id=str(event_id),
            summary=f'Deleted event "{event.title}"',
        )

    @patch(
        "/{event_id:uuid}/signups/{signup_id:uuid}",
        operation_id="UpdateEventChart",
        tags=["Event scheduling"],
        security=SECURITY_SESSION,
        summary="Set a raid chart slot",
        description=(
            "Places a signed-up player into a raid chart group (1 to 8) or the bench. An officer must be signed "
            "in. Returns 409 for any event that is not a raid."
        ),
        response_description="The updated signup.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="No event or no signup with that ID."),
            409: ResponseSpec(None, description="The raid chart only applies to raid events."),
        },
    )
    async def update_event_chart(
        self,
        event_id: _EVENT_ID,
        signup_id: Annotated[UUID, Parameter(description="The signup's ID.")],
        data: JSONBody[ChartUpdate],
        event_signups_service: NamedDependency[EventSignupsService],
        current_officer: NamedDependency[Member],
    ) -> Signup:
        signup = await event_signups_service.update_chart(event_id, signup_id, data)
        if data.bench:
            summary = f"Benched {signup.member.display_name} on the raid chart"
        elif data.group is not None:
            summary = f"Placed {signup.member.display_name} in chart group {data.group}"
        else:
            summary = f"Updated {signup.member.display_name}'s raid chart slot"
        await record_officer_audit(
            event_signups_service.repository.session,
            actor=current_officer,
            action="event.chart",
            subject_type="event",
            subject_id=str(event_id),
            summary=summary,
        )
        return signup
