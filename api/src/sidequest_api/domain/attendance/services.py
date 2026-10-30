"""Event attendance: officer marking, bot-reported voice minutes, and the GM attendance report/trends."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

from litestar.exceptions import HTTPException, NotFoundException, ValidationException
from litestar.status_codes import HTTP_409_CONFLICT
from sqlalchemy import select

from sidequest_api.lib.attendance import (
    SEASON_START,
    VOICE_PRESENT_THRESHOLD_MINUTES,
    attended_condition,
    no_show_condition,
)
from sidequest_api.lib.discord import avatar_url
from sidequest_common.models import EventSignup, EventVoicePresence, GuildEvent, Member
from sidequest_common.schemas import (
    AttendanceDetail,
    AttendanceEventSummary,
    AttendanceMark,
    AttendanceRange,
    AttendanceReport,
    AttendanceSignup,
    AttendanceTrendPoint,
    AttendanceTrends,
    EventKind,
    MemberAttendanceRow,
    VoicePresenceEntry,
    VoicePresenceReport,
    WalkInCandidate,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.engine import Row
    from sqlalchemy.ext.asyncio import AsyncSession

PAST_EVENT_LIMIT = 50
_ROLE_KIND_VALUES = {"raid", "dungeon"}
_ALL_TIME_START = datetime(2020, 1, 1, tzinfo=UTC)


@dataclass
class _MemberBucket:
    """Running totals for one member's row in ``AttendanceReport``."""

    signed_up: int = 0
    came: int = 0
    no_shows: int = 0
    walk_ins: int = 0
    attended_signed: int = 0
    """Signed (non-walk-in) sign-ups that were attended: the ``attendance_rate`` numerator."""
    last_attended: datetime | None = None


@dataclass
class _WeekBucket:
    """Running totals for one week's point on ``AttendanceTrends``."""

    attendees: set[int] = field(default_factory=set)
    signed_up: int = 0
    attended_signed: int = 0
    """Signed (non-walk-in) sign-ups that were attended: the ``show_rate`` numerator."""


def _needs_attendance(event: GuildEvent, *, now: datetime) -> bool:
    return event.starts_at < now and event.status != "cancelled" and event.attendance_taken_at is None


def _event_summary(event: GuildEvent, *, now: datetime) -> AttendanceEventSummary:
    return AttendanceEventSummary(
        id=event.id,
        title=event.title,
        kind=EventKind(event.kind),
        starts_at=event.starts_at,
        status=event.status,
        attendance_taken_at=event.attendance_taken_at,
        needs_attendance=_needs_attendance(event, now=now),
    )


def _range_bounds(attendance_range: AttendanceRange, *, now: datetime) -> tuple[datetime, datetime]:
    if attendance_range == AttendanceRange.LAST_30:
        start = now - timedelta(days=30)
    elif attendance_range == AttendanceRange.SEASON:
        start = datetime.combine(SEASON_START, time.min, tzinfo=UTC)
    else:
        start = _ALL_TIME_START
    return start, now


class AttendanceService:
    """Everything the attendance tab reads or writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """The request's session, for the controller's ``attendance.mark`` audit write."""
        return self._session

    # --- Officer: recent events + marking screen --------------------------------------------------------------

    async def list_recent_events(
        self, *, kind: EventKind | None = None, limit: int = PAST_EVENT_LIMIT
    ) -> list[AttendanceEventSummary]:
        """Past, non-cancelled events, most recent first, with a "needs attendance" marker."""
        now = datetime.now(UTC)
        statement = (
            select(GuildEvent)
            .where(GuildEvent.starts_at < now, GuildEvent.status != "cancelled")
            .order_by(GuildEvent.starts_at.desc())
            .limit(limit)
        )
        if kind is not None:
            statement = statement.where(GuildEvent.kind == kind.value)
        events = (await self._session.execute(statement)).scalars().all()
        return [_event_summary(event, now=now) for event in events]

    async def get_event_or_404(self, event_id: UUID) -> GuildEvent:
        """The event, or 404."""
        event = await self._session.get(GuildEvent, event_id)
        if event is None:
            msg = f"No event {event_id}"
            raise NotFoundException(msg)
        return event

    async def _voice_minutes_for(self, event_id: UUID) -> dict[int, int]:
        statement = select(EventVoicePresence.discord_id, EventVoicePresence.minutes).where(
            EventVoicePresence.event_id == event_id
        )
        return dict((await self._session.execute(statement)).tuples().all())

    def _to_attendance_signup(
        self, signup: EventSignup, member: Member, voice_minutes: int, event: GuildEvent
    ) -> AttendanceSignup:
        if event.attendance_taken_at is not None:
            suggested = bool(signup.attended)
        else:
            suggested = signup.status == "signed" or voice_minutes >= VOICE_PRESENT_THRESHOLD_MINUTES
        return AttendanceSignup(
            signup_id=signup.id,
            member_id=member.id,
            display_name=member.display_name,
            avatar_url=avatar_url(member.discord_id, member.avatar_hash),
            character=signup.character,
            wow_class=signup.wow_class,
            role=signup.role,
            status=signup.status,
            attended=signup.attended,
            is_walk_in=signup.is_walk_in,
            voice_minutes=voice_minutes,
            suggested_attended=suggested,
        )

    async def get_detail(self, event_id: UUID) -> AttendanceDetail:
        """The marking screen for one event: roster, bot-reported voice minutes, and walk-in candidates."""
        event = await self.get_event_or_404(event_id)
        rows = (
            await self._session.execute(
                select(EventSignup, Member)
                .join(Member, EventSignup.member_id == Member.id)
                .where(EventSignup.event_id == event_id)
            )
        ).all()
        voice_minutes = await self._voice_minutes_for(event_id)
        signups = [
            self._to_attendance_signup(signup, member, voice_minutes.get(member.discord_id, 0), event)
            for signup, member in rows
        ]
        signed_up_ids = {member.id for _, member in rows}
        all_members_stmt = select(Member).where(Member.is_guild_member.is_(True))
        all_members = (await self._session.execute(all_members_stmt)).scalars().all()
        candidates = sorted(
            (member for member in all_members if member.id not in signed_up_ids),
            key=lambda member: member.display_name.casefold(),
        )
        return AttendanceDetail(
            event=_event_summary(event, now=datetime.now(UTC)),
            signups=sorted(signups, key=lambda row: row.display_name.casefold()),
            walk_in_candidates=[
                WalkInCandidate(
                    member_id=member.id,
                    display_name=member.display_name,
                    avatar_url=avatar_url(member.discord_id, member.avatar_hash),
                )
                for member in candidates
            ],
        )

    async def mark_attendance(self, event_id: UUID, data: AttendanceMark) -> AttendanceDetail:
        """Apply Came/No-show marks and create walk-ins, then set ``attendance_taken_at`` to now.

        409 if the event hasn't started yet or is cancelled, or a walk-in duplicates an existing sign-up. 404
        unknown sign-up/member. 400 if a walk-in for a raid/dungeon event is missing character/class/role.
        """
        event = await self.get_event_or_404(event_id)
        now = datetime.now(UTC)
        if event.starts_at >= now:
            msg = "Attendance can only be taken for events that have started"
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg)
        if event.status == "cancelled":
            msg = "Attendance can't be taken for a cancelled event"
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg)
        signups_stmt = select(EventSignup).where(EventSignup.event_id == event_id)
        signups = (await self._session.execute(signups_stmt)).scalars().all()
        signups_by_id = {signup.id: signup for signup in signups}
        existing_member_ids = {signup.member_id for signup in signups}
        for entry in data.entries:
            signup = signups_by_id.get(entry.signup_id)
            if signup is None:
                msg = f"No signup {entry.signup_id} on event {event_id}"
                raise NotFoundException(msg)
            signup.attended = entry.attended
        is_role_kind = event.kind in _ROLE_KIND_VALUES
        for walk_in in data.walk_ins:
            if walk_in.member_id in existing_member_ids:
                msg = f"Member {walk_in.member_id} already has a sign-up for this event"
                raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg)
            if is_role_kind and (walk_in.character is None or walk_in.wow_class is None or walk_in.role is None):
                msg = "character, class, and role are required for this event's kind"
                raise ValidationException(msg)
            member = await self._session.get(Member, walk_in.member_id)
            if member is None:
                msg = f"No member {walk_in.member_id}"
                raise NotFoundException(msg)
            self._session.add(
                EventSignup(
                    event_id=event_id,
                    member_id=walk_in.member_id,
                    character=walk_in.character,
                    wow_class=walk_in.wow_class.value if walk_in.wow_class is not None else None,
                    role=walk_in.role.value if walk_in.role is not None else None,
                    status="signed",
                    attended=True,
                    is_walk_in=True,
                )
            )
            existing_member_ids.add(walk_in.member_id)
        event.attendance_taken_at = now
        await self._session.commit()
        return await self.get_detail(event_id)

    # --- Bot: voice presence -----------------------------------------------------------------------------------

    async def upsert_voice_presence(self, report: VoicePresenceReport) -> None:
        """Raise the stored cumulative voice minutes for each listed member on ``report.event_id`` to ``max``.

        Never lowers a stored total: a worker restart resets its own in-memory counter to 0, and a report from a
        freshly-restarted worker must not erase minutes already accumulated by the previous process.
        """
        event = await self._session.get(GuildEvent, report.event_id)
        if event is None:
            msg = f"No event {report.event_id}"
            raise NotFoundException(msg)
        if not report.entries:
            return
        discord_ids = [int(entry.discord_id) for entry in report.entries]
        existing_statement = select(EventVoicePresence).where(
            EventVoicePresence.event_id == report.event_id, EventVoicePresence.discord_id.in_(discord_ids)
        )
        existing = {row.discord_id: row for row in (await self._session.execute(existing_statement)).scalars().all()}
        for entry in report.entries:
            discord_id = int(entry.discord_id)
            row = existing.get(discord_id)
            if row is None:
                self._session.add(
                    EventVoicePresence(event_id=report.event_id, discord_id=discord_id, minutes=entry.minutes)
                )
            else:
                row.minutes = max(row.minutes, entry.minutes)
        await self._session.commit()

    async def get_voice_presence(self, event_id: UUID) -> VoicePresenceReport:
        """The stored cumulative voice minutes per member for ``event_id``, so a restarted bot can resume them."""
        minutes = await self._voice_minutes_for(event_id)
        return VoicePresenceReport(
            event_id=event_id,
            entries=[
                VoicePresenceEntry(discord_id=str(discord_id), minutes=member_minutes)
                for discord_id, member_minutes in minutes.items()
            ],
        )

    # --- GM: report and trends -----------------------------------------------------------------------------------

    async def _attendance_rows(self, attendance_range: AttendanceRange, *, raids_only: bool) -> list[Row]:
        now = datetime.now(UTC)
        start, end = _range_bounds(attendance_range, now=now)
        statement = (
            select(
                EventSignup.member_id,
                GuildEvent.starts_at,
                EventSignup.status,
                EventSignup.is_walk_in,
                attended_condition(now=now).label("came"),
                no_show_condition().label("no_show"),
            )
            .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
            .where(GuildEvent.starts_at >= start, GuildEvent.starts_at < end, GuildEvent.status != "cancelled")
        )
        if raids_only:
            statement = statement.where(GuildEvent.kind == "raid")
        return list((await self._session.execute(statement)).all())

    async def _members_by_id(self, member_ids: list[int]) -> dict[int, Member]:
        if not member_ids:
            return {}
        rows = (await self._session.execute(select(Member).where(Member.id.in_(member_ids)))).scalars().all()
        return {member.id: member for member in rows}

    async def report(self, attendance_range: AttendanceRange, *, raids_only: bool) -> AttendanceReport:
        """Per-member sign-ups/attendance within ``attendance_range``, display-name sorted."""
        rows = await self._attendance_rows(attendance_range, raids_only=raids_only)
        stats: dict[int, _MemberBucket] = {}
        for member_id, starts_at, status, is_walk_in, came, no_show in rows:
            bucket = stats.setdefault(member_id, _MemberBucket())
            if is_walk_in:
                bucket.walk_ins += 1
            elif status == "signed":
                bucket.signed_up += 1
                if came:
                    bucket.attended_signed += 1
            if came:
                bucket.came += 1
                if bucket.last_attended is None or starts_at > bucket.last_attended:
                    bucket.last_attended = starts_at
            if no_show:
                bucket.no_shows += 1
        members = await self._members_by_id(list(stats.keys()))
        result_rows = []
        for member_id, bucket in stats.items():
            member = members.get(member_id)
            if member is None:
                continue
            result_rows.append(
                MemberAttendanceRow(
                    member_id=member_id,
                    display_name=member.display_name,
                    avatar_url=avatar_url(member.discord_id, member.avatar_hash),
                    signed_up=bucket.signed_up,
                    came=bucket.came,
                    no_shows=bucket.no_shows,
                    walk_ins=bucket.walk_ins,
                    attendance_rate=(bucket.attended_signed / bucket.signed_up) if bucket.signed_up else 0.0,
                    last_attended=bucket.last_attended,
                )
            )
        result_rows.sort(key=lambda row: row.display_name.casefold())
        return AttendanceReport(range=attendance_range, raids_only=raids_only, rows=result_rows)

    async def trends(self, attendance_range: AttendanceRange, *, raids_only: bool) -> AttendanceTrends:
        """Weekly (Monday-start) distinct attendees and show rate within ``attendance_range``, oldest week first."""
        rows = await self._attendance_rows(attendance_range, raids_only=raids_only)
        weeks: dict[date, _WeekBucket] = {}
        for member_id, starts_at, status, is_walk_in, came, no_show in rows:
            del no_show
            week_start = starts_at.date() - timedelta(days=starts_at.weekday())
            bucket = weeks.setdefault(week_start, _WeekBucket())
            if not is_walk_in and status == "signed":
                bucket.signed_up += 1
                if came:
                    bucket.attended_signed += 1
            if came:
                bucket.attendees.add(member_id)
        points = [
            AttendanceTrendPoint(
                week_start=week_start,
                attendees=len(bucket.attendees),
                signed_up=bucket.signed_up,
                show_rate=(bucket.attended_signed / bucket.signed_up) if bucket.signed_up else 0.0,
            )
            for week_start, bucket in sorted(weeks.items())
        ]
        return AttendanceTrends(range=attendance_range, raids_only=raids_only, points=points)
