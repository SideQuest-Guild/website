"""Event attendance: officer marking, the GM attendance report/trends, and the bot's voice-minutes push.

Session-gated routes use dependency-based gating (``current_officer``/``current_gm``, registered app-wide in
``create_app``): declaring the parameter resolves it, raising 401/403 before the handler body runs.
``AttendanceVoiceController`` is bot-key only (mounted under ``/api/guilds/{guild_id}``, same rule as
``DiscordLiveController``: every route 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID``).
"""

from typing import Annotated
from uuid import UUID

from litestar import Controller, get, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.attendance.dependencies import provide_attendance_service
from sidequest_api.domain.attendance.services import AttendanceService
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import (
    NOT_A_GM,
    NOT_AN_OFFICER,
    NOT_SIGNED_IN,
    SECURITY_SESSION,
    GuildIdPath,
    ResponseSpec,
)
from sidequest_common.models import Member
from sidequest_common.schemas import (
    AttendanceDetail,
    AttendanceEventSummary,
    AttendanceMark,
    AttendanceRange,
    AttendanceReport,
    AttendanceTrends,
    EventKind,
    VoicePresenceReport,
)
from sidequest_common.settings import WebSettings


def _mark_summary(event_title: str, data: AttendanceMark) -> str:
    came = sum(1 for entry in data.entries if entry.attended) + len(data.walk_ins)
    no_shows = sum(1 for entry in data.entries if not entry.attended)
    summary = f'Took attendance for "{event_title}": {came} came, {no_shows} no-show'
    if data.walk_ins:
        summary += f", {len(data.walk_ins)} walk-in" + ("s" if len(data.walk_ins) != 1 else "")
    return summary


class AttendanceController(Controller):
    """``/api/attendance`` (officer event list, GM report/trends) and ``/api/events/{id}/attendance`` (officer)."""

    path = "/api"
    dependencies = {"attendance_service": Provide(provide_attendance_service)}

    @get(
        "/attendance/events",
        operation_id="ListAttendanceEvents",
        tags=["Attendance"],
        security=SECURITY_SESSION,
        summary="List events needing attendance",
        description="Returns recent past events with a marker for whether they still need attendance taken.",
        response_description="The recent events, newest first.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def list_events(
        self,
        current_officer: NamedDependency[Member],
        attendance_service: NamedDependency[AttendanceService],
        kind: Annotated[EventKind | None, Parameter(description="Only list events of this kind.")] = None,
    ) -> list[AttendanceEventSummary]:
        del current_officer
        return await attendance_service.list_recent_events(kind=kind)

    @get(
        "/events/{event_id:uuid}/attendance",
        operation_id="GetEventAttendance",
        tags=["Attendance"],
        security=SECURITY_SESSION,
        summary="Get an event's attendance marking screen",
        description=(
            "Returns one event's roster, bot-reported voice minutes, and walk-in candidates for marking attendance."
        ),
        response_description="The event's attendance detail.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER, 404: ResponseSpec(None, description="Unknown event.")},
    )
    async def get_attendance(
        self,
        event_id: Annotated[UUID, Parameter(description="The event's ID.")],
        current_officer: NamedDependency[Member],
        attendance_service: NamedDependency[AttendanceService],
    ) -> AttendanceDetail:
        del current_officer
        return await attendance_service.get_detail(event_id)

    @put(
        "/events/{event_id:uuid}/attendance",
        operation_id="MarkEventAttendance",
        tags=["Attendance"],
        security=SECURITY_SESSION,
        summary="Mark an event's attendance",
        description=(
            "Records Came or No-show for each sign-up and any walk-ins, and sets `attendance_taken_at`. Writes "
            "an `attendance.mark` audit row."
        ),
        response_description="The event's updated attendance detail.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="Unknown event, sign-up, or member."),
            409: ResponseSpec(
                None,
                description=(
                    "The event has not started yet, is cancelled, or a walk-in duplicates an existing sign-up."
                ),
            ),
            400: ResponseSpec(
                None, description="A walk-in for a raid or dungeon event is missing character, class, or role."
            ),
        },
    )
    async def mark_attendance(
        self,
        event_id: Annotated[UUID, Parameter(description="The event's ID.")],
        data: JSONBody[AttendanceMark],
        current_officer: NamedDependency[Member],
        attendance_service: NamedDependency[AttendanceService],
    ) -> AttendanceDetail:
        event = await attendance_service.get_event_or_404(event_id)
        title = event.title
        detail = await attendance_service.mark_attendance(event_id, data)
        await record_officer_audit(
            attendance_service.session,
            actor=current_officer,
            action="attendance.mark",
            subject_type="event",
            subject_id=str(event_id),
            summary=_mark_summary(title, data),
        )
        return detail

    @get(
        "/attendance/report",
        operation_id="GetAttendanceReport",
        tags=["Attendance reports"],
        security=SECURITY_SESSION,
        summary="Get the attendance report",
        description="Returns per-member attendance counts over a window.",
        response_description="The attendance report.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_GM},
    )
    async def get_report(
        self,
        current_gm: NamedDependency[Member],
        attendance_service: NamedDependency[AttendanceService],
        window: Annotated[AttendanceRange, Parameter(description="The time window to report over.")] = (
            AttendanceRange.LAST_30
        ),
        raids_only: Annotated[  # noqa: FBT002 - query param, not a regular default
            bool, Parameter(description="Only count raid events.")
        ] = False,
    ) -> AttendanceReport:
        del current_gm
        return await attendance_service.report(window, raids_only=raids_only)

    @get(
        "/attendance/trends",
        operation_id="GetAttendanceTrends",
        tags=["Attendance reports"],
        security=SECURITY_SESSION,
        summary="Get attendance trends",
        description="Returns weekly distinct attendees and show rate over a window, oldest week first.",
        response_description="The attendance trends.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_GM},
    )
    async def get_trends(
        self,
        current_gm: NamedDependency[Member],
        attendance_service: NamedDependency[AttendanceService],
        window: Annotated[AttendanceRange, Parameter(description="The time window to report over.")] = (
            AttendanceRange.SEASON
        ),
        raids_only: Annotated[  # noqa: FBT002 - query param, not a regular default
            bool, Parameter(description="Only count raid events.")
        ] = False,
    ) -> AttendanceTrends:
        del current_gm
        return await attendance_service.trends(window, raids_only=raids_only)


class AttendanceVoiceController(Controller):
    """``/api/guilds/{guild_id}/attendance/voice``: the bot reports voice-channel minutes per running event."""

    path = "/attendance/voice"
    tags = ["Attendance voice"]
    dependencies = {"attendance_service": Provide(provide_attendance_service)}

    @put(
        "/",
        operation_id="ReportVoicePresence",
        status_code=204,
        summary="Report voice presence",
        description=(
            "Raises the stored cumulative voice minutes for each listed member to the reported max. Never "
            "lowers a stored total. Returns 404 for any guild_id other than the SideQuest server, or an "
            "unknown event."
        ),
        response_description="The voice presence report was applied.",
        responses={
            404: ResponseSpec(
                None, description="This guild_id is not the SideQuest server, or the event does not exist."
            )
        },
    )
    async def report_voice_presence(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[VoicePresenceReport],
        attendance_service: NamedDependency[AttendanceService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        if guild_id != web_settings.GUILD_ID:
            msg = f"No guild {guild_id}"
            raise NotFoundException(msg)
        await attendance_service.upsert_voice_presence(data)

    @get(
        "/{event_id:uuid}",
        operation_id="GetVoicePresence",
        summary="Get voice presence",
        description=(
            "Returns current cumulative voice minutes per member for an event, so a restarted bot can resume "
            "tracking. Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The event's voice presence totals.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server.")},
    )
    async def get_voice_presence(
        self,
        guild_id: GuildIdPath,
        event_id: Annotated[UUID, Parameter(description="The event's ID.")],
        attendance_service: NamedDependency[AttendanceService],
        web_settings: NamedDependency[WebSettings],
    ) -> VoicePresenceReport:
        if guild_id != web_settings.GUILD_ID:
            msg = f"No guild {guild_id}"
            raise NotFoundException(msg)
        return await attendance_service.get_voice_presence(event_id)
