"""Group voice channels (LFG): bot session lifecycle, officer stats/session list, and the public leaderboard.

Snowflakes travel as strings on the wire (``GroupSessionCreate.discord_channel_id`` and friends); stored as
``BigInteger`` in the database. ``_merge_presence`` mirrors ``AttendanceService.upsert_voice_presence``: every
number is stored as ``max(existing, reported)``, so a restarted bot (resuming counters from ``GroupSessionSchema``)
can never erase progress, and closing an already-closed session (``close_session``) only ever merges presence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_409_CONFLICT
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from sidequest_common.models import GroupSession, GroupSessionMember, GroupSessionPair, GroupSessionTranscript, Member
from sidequest_common.schemas import (
    COUNTED_GROUP_MINUTES,
    GROUP_TRANSCRIPT_RETENTION_DAYS,
    EventKind,
    GroupDuoStat,
    GroupEndReason,
    GroupHourStat,
    GroupInstanceStat,
    GroupKindStat,
    GroupLeaderboard,
    GroupLeaderboardRow,
    GroupMemberMinutes,
    GroupPairMinutes,
    GroupPerson,
    GroupPersonStat,
    GroupPresenceReport,
    GroupSessionClose,
    GroupSessionCreate,
    GroupSessionDetail,
    GroupSessionSchema,
    GroupSessionSummary,
    GroupSessionUpdate,
    GroupStats,
    GroupTranscriptMessage,
    GroupTranscriptPurge,
    SignupRole,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

GUILD_TZ = ZoneInfo("America/Chicago")
_LEADERBOARD_WINDOW_DAYS = 30
_TOP_N = 10
MIN_COUNTED_PEAK_SIZE = 2
"""A session counts toward stats only once two or more members were ever present together."""


def _group_person(
    discord_id: int, *, member_by_discord_id: dict[int, Member], fallback_name: str = "Unknown"
) -> GroupPerson:
    linked = member_by_discord_id.get(discord_id)
    if linked is not None:
        return GroupPerson(discord_id=str(discord_id), display_name=linked.display_name, member_id=linked.id)
    return GroupPerson(discord_id=str(discord_id), display_name=fallback_name)


def _session_schema(
    session: GroupSession, members: list[GroupSessionMember], pairs: list[GroupSessionPair]
) -> GroupSessionSchema:
    return GroupSessionSchema(
        id=session.id,
        discord_channel_id=str(session.discord_channel_id),
        channel_name=session.channel_name,
        kind=EventKind(session.kind),
        name=session.name,
        note=session.note,
        needs=[SignupRole(need) for need in session.needs],
        cap=session.cap,
        creator_discord_id=str(session.creator_discord_id),
        owner_discord_id=str(session.owner_discord_id),
        event_id=session.event_id,
        card_message_id=str(session.card_message_id) if session.card_message_id is not None else None,
        pug_role_id=str(session.pug_role_id) if session.pug_role_id is not None else None,
        started_at=session.started_at,
        ended_at=session.ended_at,
        end_reason=GroupEndReason(session.end_reason) if session.end_reason is not None else None,
        peak_size=session.peak_size,
        grouped_minutes=session.grouped_minutes,
        pug_minutes=session.pug_minutes,
        members=[
            GroupMemberMinutes(
                discord_id=str(member.discord_id), display_name=member.display_name, minutes=member.minutes
            )
            for member in members
        ],
        pairs=[
            GroupPairMinutes(
                discord_id_a=str(pair.discord_id_a), discord_id_b=str(pair.discord_id_b), minutes=pair.minutes
            )
            for pair in pairs
        ],
    )


def _is_counted(session: GroupSession) -> bool:
    return session.peak_size >= MIN_COUNTED_PEAK_SIZE and session.grouped_minutes >= COUNTED_GROUP_MINUTES


class GroupsService:
    """Everything the ``#lfg`` panel, group channel controls, and officer/public stats read or write."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Bot: session lifecycle ----------------------------------------------------------------------------------

    async def create_session(self, data: GroupSessionCreate) -> GroupSessionSchema:
        """A new group channel's session row. 409 if the channel id already has a session."""
        session = GroupSession(
            discord_channel_id=int(data.discord_channel_id),
            channel_name=data.channel_name,
            kind=data.kind.value,
            name=data.name,
            note=data.note,
            needs=[need.value for need in data.needs],
            cap=data.cap,
            creator_discord_id=int(data.creator_discord_id),
            owner_discord_id=int(data.creator_discord_id),
            event_id=data.event_id,
            card_message_id=int(data.card_message_id) if data.card_message_id is not None else None,
            pug_role_id=int(data.pug_role_id) if data.pug_role_id is not None else None,
            started_at=datetime.now(UTC),
        )
        self._session.add(session)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            msg = f"Channel {data.discord_channel_id} already has a group session"
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg) from exc
        await self._session.refresh(session)
        return _session_schema(session, [], [])

    async def _get_or_404(self, session_id: UUID) -> GroupSession:
        session = await self._session.get(GroupSession, session_id)
        if session is None:
            msg = f"No group session {session_id}"
            raise NotFoundException(msg)
        return session

    async def _members_and_pairs(self, session_id: UUID) -> tuple[list[GroupSessionMember], list[GroupSessionPair]]:
        members = (
            (await self._session.execute(select(GroupSessionMember).where(GroupSessionMember.session_id == session_id)))
            .scalars()
            .all()
        )
        pairs = (
            (await self._session.execute(select(GroupSessionPair).where(GroupSessionPair.session_id == session_id)))
            .scalars()
            .all()
        )
        return list(members), list(pairs)

    async def get_session(self, session_id: UUID) -> GroupSessionSchema:
        """One session with its current presence, or 404."""
        session = await self._get_or_404(session_id)
        members, pairs = await self._members_and_pairs(session_id)
        return _session_schema(session, members, pairs)

    async def list_open(self) -> list[GroupSessionSchema]:
        """Open sessions (``ended_at`` null), oldest first, with presence, so a restarted bot resumes counters."""
        sessions = (
            (
                await self._session.execute(
                    select(GroupSession).where(GroupSession.ended_at.is_(None)).order_by(GroupSession.started_at)
                )
            )
            .scalars()
            .all()
        )
        if not sessions:
            return []
        session_ids = [session.id for session in sessions]
        members = (
            (
                await self._session.execute(
                    select(GroupSessionMember).where(GroupSessionMember.session_id.in_(session_ids))
                )
            )
            .scalars()
            .all()
        )
        pairs = (
            (await self._session.execute(select(GroupSessionPair).where(GroupSessionPair.session_id.in_(session_ids))))
            .scalars()
            .all()
        )
        members_by_session: dict[UUID, list[GroupSessionMember]] = {}
        for member in members:
            members_by_session.setdefault(member.session_id, []).append(member)
        pairs_by_session: dict[UUID, list[GroupSessionPair]] = {}
        for pair in pairs:
            pairs_by_session.setdefault(pair.session_id, []).append(pair)
        return [
            _session_schema(session, members_by_session.get(session.id, []), pairs_by_session.get(session.id, []))
            for session in sessions
        ]

    async def update_session(self, session_id: UUID, data: GroupSessionUpdate) -> GroupSessionSchema:
        """Apply the fields present in ``data``. ``channel_name: null`` is ignored (never clears it)."""
        session = await self._get_or_404(session_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("channel_name") is None:
            changes.pop("channel_name", None)
        for field in ("owner_discord_id", "card_message_id"):
            if field in changes and changes[field] is not None:
                changes[field] = int(changes[field])
        for field, value in changes.items():
            setattr(session, field, value)
        await self._session.commit()
        await self._session.refresh(session)
        members, pairs = await self._members_and_pairs(session_id)
        return _session_schema(session, members, pairs)

    async def _merge_presence(self, session: GroupSession, report: GroupPresenceReport) -> None:
        session.peak_size = max(session.peak_size, report.peak_size)
        session.grouped_minutes = max(session.grouped_minutes, report.grouped_minutes)
        session.pug_minutes = max(session.pug_minutes, report.pug_minutes)

        member_discord_ids = [int(entry.discord_id) for entry in report.members]
        existing_members: dict[int, GroupSessionMember] = {}
        if member_discord_ids:
            rows = (
                (
                    await self._session.execute(
                        select(GroupSessionMember).where(
                            GroupSessionMember.session_id == session.id,
                            GroupSessionMember.discord_id.in_(member_discord_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing_members = {row.discord_id: row for row in rows}
        for entry in report.members:
            discord_id = int(entry.discord_id)
            row = existing_members.get(discord_id)
            if row is None:
                self._session.add(
                    GroupSessionMember(
                        session_id=session.id,
                        discord_id=discord_id,
                        display_name=entry.display_name,
                        minutes=entry.minutes,
                    )
                )
            else:
                row.display_name = entry.display_name
                row.minutes = max(row.minutes, entry.minutes)

        existing_pairs: dict[tuple[int, int], GroupSessionPair] = {}
        if report.pairs:
            rows = (
                (await self._session.execute(select(GroupSessionPair).where(GroupSessionPair.session_id == session.id)))
                .scalars()
                .all()
            )
            existing_pairs = {(row.discord_id_a, row.discord_id_b): row for row in rows}
        for entry in report.pairs:
            key = (int(entry.discord_id_a), int(entry.discord_id_b))
            row = existing_pairs.get(key)
            if row is None:
                self._session.add(
                    GroupSessionPair(
                        session_id=session.id, discord_id_a=key[0], discord_id_b=key[1], minutes=entry.minutes
                    )
                )
            else:
                row.minutes = max(row.minutes, entry.minutes)

    async def upsert_presence(self, session_id: UUID, report: GroupPresenceReport) -> None:
        """Raise the session's stored presence to ``max(existing, reported)``. 404 for an unknown session."""
        session = await self._get_or_404(session_id)
        await self._merge_presence(session, report)
        await self._session.commit()

    async def close_session(self, session_id: UUID, data: GroupSessionClose) -> None:
        """End a session. Idempotent: closing an already-closed session only merges presence.

        Also purges any transcripts past the retention window.
        """
        session = await self._get_or_404(session_id)
        await self._merge_presence(session, data.presence)
        if session.ended_at is None:
            session.ended_at = datetime.now(UTC)
            session.end_reason = data.end_reason.value
            if data.transcript:
                self._session.add(
                    GroupSessionTranscript(
                        session_id=session.id,
                        messages=[message.model_dump(mode="json") for message in data.transcript],
                    )
                )
        await self._session.commit()
        await self.purge_transcripts()

    async def purge_transcripts(self) -> GroupTranscriptPurge:
        """Delete transcripts of sessions that ended more than ``GROUP_TRANSCRIPT_RETENTION_DAYS`` ago."""
        cutoff = datetime.now(UTC) - timedelta(days=GROUP_TRANSCRIPT_RETENTION_DAYS)
        expired_ids = (
            (
                await self._session.execute(
                    select(GroupSession.id).where(GroupSession.ended_at.is_not(None), GroupSession.ended_at < cutoff)
                )
            )
            .scalars()
            .all()
        )
        if not expired_ids:
            return GroupTranscriptPurge(deleted=0)
        transcript_session_ids = (
            (
                await self._session.execute(
                    select(GroupSessionTranscript.session_id).where(GroupSessionTranscript.session_id.in_(expired_ids))
                )
            )
            .scalars()
            .all()
        )
        if not transcript_session_ids:
            return GroupTranscriptPurge(deleted=0)
        await self._session.execute(
            delete(GroupSessionTranscript).where(GroupSessionTranscript.session_id.in_(transcript_session_ids))
        )
        await self._session.commit()
        return GroupTranscriptPurge(deleted=len(transcript_session_ids))

    # --- Officer: stats and session list ---------------------------------------------------------------------------

    async def stats(self, days: int) -> GroupStats:  # noqa: C901, PLR0915 - one cohesive report, splitting hides the shared window/counted-session state
        """Who groups, with whom, and what, over the last ``days`` days."""
        now = datetime.now(UTC)
        window_start = now - timedelta(days=days)
        sessions = (
            (await self._session.execute(select(GroupSession).where(GroupSession.started_at >= window_start)))
            .scalars()
            .all()
        )
        counted = [session for session in sessions if _is_counted(session)]
        counted_ids = [session.id for session in counted]
        sessions_by_id = {session.id: session for session in counted}

        members: list[GroupSessionMember] = []
        pairs: list[GroupSessionPair] = []
        if counted_ids:
            members = list(
                (
                    await self._session.execute(
                        select(GroupSessionMember).where(GroupSessionMember.session_id.in_(counted_ids))
                    )
                )
                .scalars()
                .all()
            )
            pairs = list(
                (
                    await self._session.execute(
                        select(GroupSessionPair).where(GroupSessionPair.session_id.in_(counted_ids))
                    )
                )
                .scalars()
                .all()
            )

        discord_ids = (
            {member.discord_id for member in members}
            | {session.creator_discord_id for session in counted}
            | {pair.discord_id_a for pair in pairs}
            | {pair.discord_id_b for pair in pairs}
        )
        member_rows = (
            (await self._session.execute(select(Member).where(Member.discord_id.in_(discord_ids)))).scalars().all()
            if discord_ids
            else []
        )
        member_by_discord_id = {member.discord_id: member for member in member_rows}
        latest_name = {member.discord_id: member.display_name for member in members}

        def person(discord_id: int) -> GroupPerson:
            return _group_person(
                discord_id,
                member_by_discord_id=member_by_discord_id,
                fallback_name=latest_name.get(discord_id, "Unknown"),
            )

        kind_totals: dict[str, dict[str, int]] = {}
        for session in counted:
            kind_totals.setdefault(session.kind, {"sessions": 0, "minutes": 0})["sessions"] += 1
        for member in members:
            kind = sessions_by_id[member.session_id].kind
            kind_totals.setdefault(kind, {"sessions": 0, "minutes": 0})["minutes"] += member.minutes
        by_kind = [
            GroupKindStat(kind=EventKind(kind), sessions=row["sessions"], minutes=row["minutes"])
            for kind, row in sorted(kind_totals.items())
        ]

        instance_names: dict[tuple[str, str], str] = {}
        instance_sessions: dict[tuple[str, str], int] = {}
        for session in counted:
            if not session.name:
                continue
            key = (session.kind, session.name.casefold())
            instance_names.setdefault(key, session.name)
            instance_sessions[key] = instance_sessions.get(key, 0) + 1
        top_instances = sorted(
            (
                GroupInstanceStat(kind=EventKind(key[0]), name=instance_names[key], sessions=sessions)
                for key, sessions in instance_sessions.items()
            ),
            key=lambda stat: stat.sessions,
            reverse=True,
        )[:_TOP_N]

        minutes_by_discord_id: dict[int, int] = {}
        qualifying_sessions_by_discord_id: dict[int, int] = {}
        for member in members:
            minutes_by_discord_id[member.discord_id] = minutes_by_discord_id.get(member.discord_id, 0) + member.minutes
            if member.minutes >= COUNTED_GROUP_MINUTES:
                qualifying_sessions_by_discord_id[member.discord_id] = (
                    qualifying_sessions_by_discord_id.get(member.discord_id, 0) + 1
                )
        most_grouped = sorted(
            (
                GroupPersonStat(
                    person=person(discord_id),
                    value=minutes,
                    sessions=qualifying_sessions_by_discord_id.get(discord_id, 0),
                )
                for discord_id, minutes in minutes_by_discord_id.items()
            ),
            key=lambda stat: stat.value,
            reverse=True,
        )[:_TOP_N]

        partners_by_discord_id: dict[int, set[int]] = {}
        pair_minutes: dict[tuple[int, int], int] = {}
        pair_sessions: dict[tuple[int, int], int] = {}
        for pair in pairs:
            if pair.minutes < COUNTED_GROUP_MINUTES:
                continue
            partners_by_discord_id.setdefault(pair.discord_id_a, set()).add(pair.discord_id_b)
            partners_by_discord_id.setdefault(pair.discord_id_b, set()).add(pair.discord_id_a)
            key = (pair.discord_id_a, pair.discord_id_b)
            pair_minutes[key] = pair_minutes.get(key, 0) + pair.minutes
            pair_sessions[key] = pair_sessions.get(key, 0) + 1
        most_social = sorted(
            (
                GroupPersonStat(
                    person=person(discord_id),
                    value=len(partners),
                    sessions=qualifying_sessions_by_discord_id.get(discord_id, 0),
                )
                for discord_id, partners in partners_by_discord_id.items()
            ),
            key=lambda stat: stat.value,
            reverse=True,
        )[:_TOP_N]
        best_duos = sorted(
            (
                GroupDuoStat(a=person(a_id), b=person(b_id), minutes=minutes, sessions=pair_sessions[(a_id, b_id)])
                for (a_id, b_id), minutes in pair_minutes.items()
            ),
            key=lambda stat: stat.minutes,
            reverse=True,
        )[:_TOP_N]

        created_counts: dict[int, int] = {}
        for session in counted:
            created_counts[session.creator_discord_id] = created_counts.get(session.creator_discord_id, 0) + 1
        most_led = sorted(
            (
                GroupPersonStat(person=person(discord_id), value=count, sessions=count)
                for discord_id, count in created_counts.items()
            ),
            key=lambda stat: stat.value,
            reverse=True,
        )[:_TOP_N]

        hour_counts: dict[tuple[int, int], int] = {}
        for session in counted:
            local = session.started_at.astimezone(GUILD_TZ)
            key = (local.weekday(), local.hour)
            hour_counts[key] = hour_counts.get(key, 0) + 1
        busy_hours = sorted(
            (
                GroupHourStat(weekday=weekday, hour=hour, sessions=count)
                for (weekday, hour), count in hour_counts.items()
            ),
            key=lambda stat: (-stat.sessions, stat.weekday, stat.hour),
        )[:_TOP_N]

        return GroupStats(
            days=days,
            sessions_total=len(sessions),
            sessions_counted=len(counted),
            grouped_minutes=sum(session.grouped_minutes for session in counted),
            by_kind=by_kind,
            top_instances=top_instances,
            most_grouped=most_grouped,
            most_social=most_social,
            best_duos=best_duos,
            most_led=most_led,
            busy_hours=busy_hours,
        )

    async def list_sessions(self, *, limit: int, before: datetime | None) -> list[GroupSessionSummary]:
        """Open and closed sessions, newest first, capped at ``limit``."""
        statement = select(GroupSession).order_by(GroupSession.started_at.desc()).limit(limit)
        if before is not None:
            statement = statement.where(GroupSession.started_at < before)
        sessions = (await self._session.execute(statement)).scalars().all()
        if not sessions:
            return []
        session_ids = [session.id for session in sessions]
        transcript_session_ids = set(
            (
                await self._session.execute(
                    select(GroupSessionTranscript.session_id).where(GroupSessionTranscript.session_id.in_(session_ids))
                )
            )
            .scalars()
            .all()
        )
        discord_ids = {session.creator_discord_id for session in sessions}
        member_rows = (
            (await self._session.execute(select(Member).where(Member.discord_id.in_(discord_ids)))).scalars().all()
            if discord_ids
            else []
        )
        member_by_discord_id = {member.discord_id: member for member in member_rows}
        name_rows = (
            await self._session.execute(
                select(
                    GroupSessionMember.session_id, GroupSessionMember.discord_id, GroupSessionMember.display_name
                ).where(GroupSessionMember.session_id.in_(session_ids))
            )
        ).all()
        creator_names = {(session_id, discord_id): display_name for session_id, discord_id, display_name in name_rows}

        def creator_person(session: GroupSession) -> GroupPerson:
            fallback = creator_names.get((session.id, session.creator_discord_id), "Unknown")
            return _group_person(
                session.creator_discord_id, member_by_discord_id=member_by_discord_id, fallback_name=fallback
            )

        return [
            GroupSessionSummary(
                id=session.id,
                kind=EventKind(session.kind),
                name=session.name,
                channel_name=session.channel_name,
                creator=creator_person(session),
                event_id=session.event_id,
                started_at=session.started_at,
                ended_at=session.ended_at,
                end_reason=GroupEndReason(session.end_reason) if session.end_reason is not None else None,
                peak_size=session.peak_size,
                grouped_minutes=session.grouped_minutes,
                counted=_is_counted(session),
                has_transcript=session.id in transcript_session_ids,
            )
            for session in sessions
        ]

    async def get_session_detail(self, session_id: UUID) -> GroupSessionDetail:
        """One session with who was in it and its chat, if still kept. 404 for an unknown session."""
        session = await self._get_or_404(session_id)
        members, _pairs = await self._members_and_pairs(session_id)
        discord_ids = {member.discord_id for member in members} | {session.creator_discord_id}
        member_rows = (
            (await self._session.execute(select(Member).where(Member.discord_id.in_(discord_ids)))).scalars().all()
        )
        member_by_discord_id = {member.discord_id: member for member in member_rows}
        name_by_discord_id = {member.discord_id: member.display_name for member in members}
        creator = _group_person(
            session.creator_discord_id,
            member_by_discord_id=member_by_discord_id,
            fallback_name=name_by_discord_id.get(session.creator_discord_id, "Unknown"),
        )

        transcript_row = (
            await self._session.execute(
                select(GroupSessionTranscript).where(GroupSessionTranscript.session_id == session_id)
            )
        ).scalar_one_or_none()
        transcript_expires_at = (
            session.ended_at + timedelta(days=GROUP_TRANSCRIPT_RETENTION_DAYS) if session.ended_at is not None else None
        )
        transcript = (
            [GroupTranscriptMessage.model_validate(message) for message in transcript_row.messages]
            if transcript_row is not None
            else None
        )

        return GroupSessionDetail(
            id=session.id,
            kind=EventKind(session.kind),
            name=session.name,
            channel_name=session.channel_name,
            creator=creator,
            event_id=session.event_id,
            started_at=session.started_at,
            ended_at=session.ended_at,
            end_reason=GroupEndReason(session.end_reason) if session.end_reason is not None else None,
            peak_size=session.peak_size,
            grouped_minutes=session.grouped_minutes,
            counted=_is_counted(session),
            has_transcript=transcript_row is not None,
            note=session.note,
            needs=[SignupRole(need) for need in session.needs],
            members=[
                GroupPersonStat(
                    person=_group_person(
                        member.discord_id, member_by_discord_id=member_by_discord_id, fallback_name=member.display_name
                    ),
                    value=member.minutes,
                    sessions=1,
                )
                for member in members
            ],
            transcript=transcript,
            transcript_expires_at=transcript_expires_at,
        )

    # --- Public: leaderboard -----------------------------------------------------------------------------------

    async def leaderboard(self) -> GroupLeaderboard:
        """Members by counted groups joined, last 30 days and all time. Only members with a site account appear."""
        month_start = datetime.now(UTC) - timedelta(days=_LEADERBOARD_WINDOW_DAYS)
        return GroupLeaderboard(
            month=await self._leaderboard_rows(window_start=month_start),
            all_time=await self._leaderboard_rows(window_start=None),
        )

    async def _leaderboard_rows(self, *, window_start: datetime | None) -> list[GroupLeaderboardRow]:
        statement = select(GroupSession)
        if window_start is not None:
            statement = statement.where(GroupSession.started_at >= window_start)
        sessions = (await self._session.execute(statement)).scalars().all()
        counted_ids = [session.id for session in sessions if _is_counted(session)]
        if not counted_ids:
            return []
        members = (
            (
                await self._session.execute(
                    select(GroupSessionMember).where(GroupSessionMember.session_id.in_(counted_ids))
                )
            )
            .scalars()
            .all()
        )
        qualifying = [member for member in members if member.minutes >= COUNTED_GROUP_MINUTES]
        if not qualifying:
            return []
        discord_ids = {member.discord_id for member in qualifying}
        member_rows = (
            (
                await self._session.execute(
                    select(Member).where(Member.discord_id.in_(discord_ids), Member.is_guild_member.is_(True))
                )
            )
            .scalars()
            .all()
        )
        member_by_discord_id = {member.discord_id: member for member in member_rows}
        groups_by_member: dict[int, int] = {}
        minutes_by_member: dict[int, int] = {}
        display_name_by_member: dict[int, str] = {}
        for member in qualifying:
            linked = member_by_discord_id.get(member.discord_id)
            if linked is None:
                continue
            groups_by_member[linked.id] = groups_by_member.get(linked.id, 0) + 1
            minutes_by_member[linked.id] = minutes_by_member.get(linked.id, 0) + member.minutes
            display_name_by_member[linked.id] = linked.display_name
        ranked = sorted(minutes_by_member.items(), key=lambda item: item[1], reverse=True)[:_TOP_N]
        return [
            GroupLeaderboardRow(
                member_id=member_id,
                display_name=display_name_by_member[member_id],
                groups=groups_by_member[member_id],
                minutes=minutes,
            )
            for member_id, minutes in ranked
        ]
