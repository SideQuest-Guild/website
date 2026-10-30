"""Event attendance: officer marking, the GM attendance report/trends, and the bot's voice-minutes push.

Session-gated routes use dependency-based gating (``current_officer``/``current_gm``, registered app-wide in
``create_app``): declaring the parameter resolves it, raising 401/403 before the handler body runs.
``AttendanceVoiceController`` is bot-key only (mounted under ``/api/guilds/{guild_id}``, same rule as
``DiscordLiveController``: every route 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID``).
"""

from uuid import UUID

from litestar import Controller, get, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, FromQuery, JSONBody

from sidequest_api.domain.attendance.dependencies import provide_attendance_service
from sidequest_api.domain.attendance.services import AttendanceService
from sidequest_api.lib.officer_audit import record_officer_audit
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
    tags = ["Attendance"]
    dependencies = {"attendance_service": Provide(provide_attendance_service)}

    @get("/attendance/events", operation_id="ListAttendanceEvents")
    async def list_events(
        self,
        current_officer: NamedDependency[Member],
        attendance_service: NamedDependency[AttendanceService],
        kind: FromQuery[EventKind | None] = None,
    ) -> list[AttendanceEventSummary]:
        """Recent past events with a "needs attendance" marker (officer). 401/403 non-officer."""
        del current_officer
        return await attendance_service.list_recent_events(kind=kind)

    @get("/events/{event_id:uuid}/attendance", operation_id="GetEventAttendance")
    async def get_attendance(
        self,
        event_id: FromPath[UUID],
        current_officer: NamedDependency[Member],
        attendance_service: NamedDependency[AttendanceService],
    ) -> AttendanceDetail:
        """The marking screen for one event: roster, bot-reported voice minutes, and walk-in candidates (officer).

        401/403 non-officer, 404 unknown event.
        """
        del current_officer
        return await attendance_service.get_detail(event_id)

    @put("/events/{event_id:uuid}/attendance", operation_id="MarkEventAttendance")
    async def mark_attendance(
        self,
        event_id: FromPath[UUID],
        data: JSONBody[AttendanceMark],
        current_officer: NamedDependency[Member],
        attendance_service: NamedDependency[AttendanceService],
    ) -> AttendanceDetail:
        """Record Came/No-show per sign-up and any walk-ins, setting ``attendance_taken_at`` (officer).

        Writes an ``attendance.mark`` audit row. 401/403 non-officer, 404 unknown event/sign-up/member, 409 if the
        event hasn't started yet, is cancelled, or a walk-in duplicates an existing sign-up, 400 if a walk-in for a
        raid/dungeon event is missing character/class/role.
        """
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

    @get("/attendance/report", operation_id="GetAttendanceReport")
    async def get_report(
        self,
        current_gm: NamedDependency[Member],
        attendance_service: NamedDependency[AttendanceService],
        window: FromQuery[AttendanceRange] = AttendanceRange.LAST_30,
        raids_only: FromQuery[bool] = False,  # noqa: FBT002 - query param, not a regular default
    ) -> AttendanceReport:
        """Per-member attendance over ``window`` (GM). 401/403 non-GM."""
        del current_gm
        return await attendance_service.report(window, raids_only=raids_only)

    @get("/attendance/trends", operation_id="GetAttendanceTrends")
    async def get_trends(
        self,
        current_gm: NamedDependency[Member],
        attendance_service: NamedDependency[AttendanceService],
        window: FromQuery[AttendanceRange] = AttendanceRange.SEASON,
        raids_only: FromQuery[bool] = False,  # noqa: FBT002 - query param, not a regular default
    ) -> AttendanceTrends:
        """Weekly distinct attendees and show rate over ``window``, oldest week first (GM). 401/403 non-GM."""
        del current_gm
        return await attendance_service.trends(window, raids_only=raids_only)


class AttendanceVoiceController(Controller):
    """``/api/guilds/{guild_id}/attendance/voice``: the bot reports voice-channel minutes per running event."""

    path = "/attendance/voice"
    tags = ["Attendance"]
    dependencies = {"attendance_service": Provide(provide_attendance_service)}

    @put("/", operation_id="ReportVoicePresence", status_code=204)
    async def report_voice_presence(
        self,
        guild_id: FromPath[int],
        data: JSONBody[VoicePresenceReport],
        attendance_service: NamedDependency[AttendanceService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """Raise the stored cumulative voice minutes for each member listed, to ``max``. 404 non-site guild/event."""
        if guild_id != web_settings.GUILD_ID:
            msg = f"No guild {guild_id}"
            raise NotFoundException(msg)
        await attendance_service.upsert_voice_presence(data)

    @get("/{event_id:uuid}", operation_id="GetVoicePresence")
    async def get_voice_presence(
        self,
        guild_id: FromPath[int],
        event_id: FromPath[UUID],
        attendance_service: NamedDependency[AttendanceService],
        web_settings: NamedDependency[WebSettings],
    ) -> VoicePresenceReport:
        """Current cumulative voice minutes per member, so a restarted bot can resume tracking. 404 non-site guild."""
        if guild_id != web_settings.GUILD_ID:
            msg = f"No guild {guild_id}"
            raise NotFoundException(msg)
        return await attendance_service.get_voice_presence(event_id)
