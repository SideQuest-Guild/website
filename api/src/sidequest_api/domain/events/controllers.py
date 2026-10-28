"""Guild event and signup endpoints: public read, member signup, officer manage (including the raid chart).

Member/officer gating is dependency-based (``current_member``/``current_officer``, registered app-wide in
``create_app``): declaring the parameter resolves it, raising 401/403 before the handler body runs.
"""

from typing import Literal
from uuid import UUID

from litestar import Controller, delete, get, patch, post, put
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, FromQuery, JSONBody

from sidequest_api.domain.events.dependencies import provide_event_signups_service, provide_events_service
from sidequest_api.domain.events.services import EventSignupsService, EventsService
from sidequest_api.lib.member_auth import provide_optional_member
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


class EventsController(Controller):
    """``/api/events``."""

    path = "/api/events"
    tags = ["Events"]
    dependencies = {
        "events_service": Provide(provide_events_service),
        "event_signups_service": Provide(provide_event_signups_service),
        "optional_member": Provide(provide_optional_member),
    }

    @get("/", operation_id="ListEvents")
    async def list_events(
        self,
        events_service: NamedDependency[EventsService],
        when: FromQuery[Literal["upcoming", "past"]] = "upcoming",
        kind: FromQuery[EventKind | None] = None,
    ) -> list[EventSummary]:
        """Events for the given window (default ``upcoming``), optionally filtered to one ``kind``."""
        return await events_service.list_summaries(when, kind)

    @get("/{event_id:uuid}", operation_id="GetEvent")
    async def get_event(
        self,
        event_id: FromPath[UUID],
        events_service: NamedDependency[EventsService],
        optional_member: NamedDependency[Member | None],
    ) -> EventDetail:
        """An event with its full roster. ``my_signup`` is the caller's own signup, if any."""
        return await events_service.get_detail(event_id, viewer=optional_member)

    @put("/{event_id:uuid}/signup", operation_id="UpsertSignup")
    async def upsert_signup(
        self,
        event_id: FromPath[UUID],
        data: JSONBody[SignupUpsert],
        event_signups_service: NamedDependency[EventSignupsService],
        current_member: NamedDependency[Member],
    ) -> Signup:
        """Create or replace the caller's signup (member). 409 if the event isn't scheduled."""
        return await event_signups_service.upsert_signup(event_id, current_member, data)

    @delete("/{event_id:uuid}/signup", operation_id="DeleteSignup")
    async def delete_signup(
        self,
        event_id: FromPath[UUID],
        event_signups_service: NamedDependency[EventSignupsService],
        current_member: NamedDependency[Member],
    ) -> None:
        """Remove the caller's signup, if any (member)."""
        await event_signups_service.delete_for_member(event_id, current_member)

    @post("/", operation_id="CreateEvent", status_code=201)
    async def create_event(
        self,
        data: JSONBody[EventCreate],
        events_service: NamedDependency[EventsService],
        current_officer: NamedDependency[Member],
    ) -> EventDetail:
        """Schedule a new guild event (officer)."""
        del current_officer
        event = await events_service.create_event(data)
        return await events_service.get_detail(event.id, viewer=None)

    @patch("/{event_id:uuid}", operation_id="UpdateEvent")
    async def update_event(
        self,
        event_id: FromPath[UUID],
        data: JSONBody[EventUpdate],
        events_service: NamedDependency[EventsService],
        current_officer: NamedDependency[Member],
    ) -> EventDetail:
        """Edit an event, including its kind and status (officer)."""
        del current_officer
        event = await events_service.update_event(event_id, data)
        return await events_service.get_detail(event.id, viewer=None)

    @delete("/{event_id:uuid}", operation_id="DeleteEvent")
    async def delete_event(
        self,
        event_id: FromPath[UUID],
        events_service: NamedDependency[EventsService],
        current_officer: NamedDependency[Member],
    ) -> None:
        """Delete an event and its signups (officer)."""
        del current_officer
        await events_service.delete_event(event_id)

    @patch("/{event_id:uuid}/signups/{signup_id:uuid}", operation_id="UpdateEventChart")
    async def update_event_chart(
        self,
        event_id: FromPath[UUID],
        signup_id: FromPath[UUID],
        data: JSONBody[ChartUpdate],
        event_signups_service: NamedDependency[EventSignupsService],
        current_officer: NamedDependency[Member],
    ) -> Signup:
        """Place a signed-up player into a raid chart group (1-8) or the bench (officer). 409 for non-raid events."""
        del current_officer
        return await event_signups_service.update_chart(event_id, signup_id, data)
