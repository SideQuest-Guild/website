"""Guild-wide server stats for the officers page.

Aggregates ``member_activity_hour`` (chat/voice minutes and the XP they earned), ``XPGrant`` (event/group XP),
attendance via ``sidequest_api.lib.attendance.attended_condition`` (the same rule Hall of Heroes and the leveling
domain use), and the counted-group rule used for group XP (``peak_size >= 2``, ``grouped_minutes``/member
``minutes >= COUNTED_GROUP_MINUTES``). Everything is pulled per window with one query per table, then aggregated
in Python, so SQLite (tests) and Postgres (prod) behave identically.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from sidequest_api.lib.attendance import attended_condition
from sidequest_api.lib.discord import avatar_url
from sidequest_common.models import (
    EventSignup,
    GroupSession,
    GroupSessionMember,
    GuildEvent,
    Member,
    MemberActivityHour,
    MemberLevel,
    XPGrant,
)
from sidequest_common.schemas import (
    COUNTED_GROUP_MINUTES,
    GuildStats,
    StatsHourCell,
    StatsLeader,
    StatsPerson,
    StatsQuietMember,
    StatsRange,
    StatsTotals,
    StatsTrendPoint,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sidequest_common.settings import WebSettings

GUILD_TZ = ZoneInfo("America/Chicago")
MIN_COUNTED_PEAK_SIZE = 2
"""A group counts toward stats only once two or more members were ever present together, like group XP."""
GONE_QUIET_DAYS = 30
"""A roster member with no activity this many days is "gone quiet", independent of the requested range."""
TOP_N = 10
GONE_QUIET_LIMIT = 25

_RANGE_DAYS: dict[StatsRange, int] = {StatsRange.SEVEN_DAYS: 7, StatsRange.THIRTY_DAYS: 30, StatsRange.NINETY_DAYS: 90}
_WEEK_BUCKET_RANGES = (StatsRange.NINETY_DAYS, StatsRange.ALL)


def _bucket_start(moment: datetime, bucket: str) -> date:
    """The day (or Monday of the week) ``moment`` falls in, America/Chicago."""
    local_date = moment.astimezone(GUILD_TZ).date()
    if bucket == "week":
        return local_date - timedelta(days=local_date.weekday())
    return local_date


class StatsService:
    """Reads behind ``GET /api/stats``: totals, trend, heatmap, leaderboards, and who's gone quiet."""

    def __init__(self, session: AsyncSession, web_settings: WebSettings) -> None:
        self._session = session
        self._guild_id = web_settings.GUILD_ID

    # --- Row selection (one query per table per window) -----------------------------------------------------

    async def _activity_rows(self, since: datetime | None, until: datetime | None) -> list[MemberActivityHour]:
        conditions = [MemberActivityHour.guild_id == self._guild_id]
        if since is not None:
            conditions.append(MemberActivityHour.hour_start >= since)
        if until is not None:
            conditions.append(MemberActivityHour.hour_start < until)
        stmt = select(MemberActivityHour).where(*conditions)
        return list((await self._session.execute(stmt)).scalars().all())

    async def _attended_rows(
        self, since: datetime | None, until: datetime | None, now: datetime
    ) -> list[tuple[int, datetime]]:
        """``(discord_id, event start)`` for attended sign-ups in ``[since, until)``."""
        conditions = [attended_condition(now=now)]
        if since is not None:
            conditions.append(GuildEvent.starts_at >= since)
        if until is not None:
            conditions.append(GuildEvent.starts_at < until)
        stmt = (
            select(Member.discord_id, GuildEvent.starts_at)
            .select_from(EventSignup)
            .join(GuildEvent, GuildEvent.id == EventSignup.event_id)
            .join(Member, Member.id == EventSignup.member_id)
            .where(*conditions)
        )
        return [(int(discord_id), starts_at) for discord_id, starts_at in (await self._session.execute(stmt)).all()]

    async def _counted_group_rows(self, since: datetime | None, until: datetime | None) -> list[tuple[int, object]]:
        """``(discord_id, session id)`` for counted #lfg groups ended in ``[since, until)``."""
        conditions = [
            GroupSession.ended_at.is_not(None),
            GroupSession.peak_size >= MIN_COUNTED_PEAK_SIZE,
            GroupSession.grouped_minutes >= COUNTED_GROUP_MINUTES,
            GroupSessionMember.minutes >= COUNTED_GROUP_MINUTES,
        ]
        if since is not None:
            conditions.append(GroupSession.ended_at >= since)
        if until is not None:
            conditions.append(GroupSession.ended_at < until)
        stmt = (
            select(GroupSessionMember.discord_id, GroupSession.id)
            .join(GroupSession, GroupSession.id == GroupSessionMember.session_id)
            .where(*conditions)
        )
        return [(int(discord_id), session_id) for discord_id, session_id in (await self._session.execute(stmt)).all()]

    async def _xp_grant_rows(self, since: datetime | None, until: datetime | None) -> list[tuple[int, int]]:
        conditions = [XPGrant.guild_id == self._guild_id]
        if since is not None:
            conditions.append(XPGrant.created_at >= since)
        if until is not None:
            conditions.append(XPGrant.created_at < until)
        stmt = select(XPGrant.user_id, XPGrant.amount).where(*conditions)
        return [(int(user_id), int(amount)) for user_id, amount in (await self._session.execute(stmt)).all()]

    # --- People -----------------------------------------------------------------------------------------------

    async def _people(self, discord_ids: set[int]) -> dict[int, StatsPerson]:
        if not discord_ids:
            return {}
        stmt = select(Member).where(Member.discord_id.in_(discord_ids))
        members = (await self._session.execute(stmt)).scalars().all()
        return {
            member.discord_id: StatsPerson(
                discord_id=str(member.discord_id),
                display_name=member.display_name,
                avatar_url=avatar_url(member.discord_id, member.avatar_hash),
                member_id=member.id,
            )
            for member in members
        }

    @staticmethod
    def _person_for(discord_id: int, people: dict[int, StatsPerson]) -> StatsPerson:
        return people.get(discord_id) or StatsPerson(discord_id=str(discord_id), display_name="Former member")

    def _top(self, counts: dict[int, int], people: dict[int, StatsPerson]) -> list[StatsLeader]:
        ordered = sorted((item for item in counts.items() if item[1] > 0), key=lambda item: (-item[1], item[0]))
        return [StatsLeader(person=self._person_for(discord_id, people), value=value) for discord_id, value in ordered][
            :TOP_N
        ]

    # --- Totals -------------------------------------------------------------------------------------------------

    async def _totals(self, since: datetime | None, until: datetime | None, now: datetime) -> StatsTotals:
        activity = await self._activity_rows(since, until)
        attended = await self._attended_rows(since, until, now)
        groups = await self._counted_group_rows(since, until)
        grants = await self._xp_grant_rows(since, until)

        active = {row.user_id for row in activity if row.messages > 0 or row.voice_minutes > 0}
        active |= {discord_id for discord_id, _ in attended}

        return StatsTotals(
            active_members=len(active),
            messages=sum(row.messages for row in activity),
            voice_minutes=sum(row.voice_minutes for row in activity),
            events_attended=len(attended),
            groups_joined=len(groups),
            xp_gained=sum(row.chat_xp + row.voice_xp for row in activity) + sum(amount for _, amount in grants),
        )

    # --- Trend and heatmap -----------------------------------------------------------------------------------

    def _build_trend(
        self,
        activity: list[MemberActivityHour],
        attended: list[tuple[int, datetime]],
        bucket: str,
        *,
        since: datetime | None,
        tracking_since: datetime | None,
        now: datetime,
    ) -> list[StatsTrendPoint]:
        start_moment = since if since is not None else tracking_since
        if start_moment is None:
            return []
        messages_by_bucket: dict[date, int] = {}
        voice_by_bucket: dict[date, int] = {}
        active_by_bucket: dict[date, set[int]] = {}
        for row in activity:
            key = _bucket_start(row.hour_start, bucket)
            messages_by_bucket[key] = messages_by_bucket.get(key, 0) + row.messages
            voice_by_bucket[key] = voice_by_bucket.get(key, 0) + row.voice_minutes
            if row.messages > 0 or row.voice_minutes > 0:
                active_by_bucket.setdefault(key, set()).add(row.user_id)
        for discord_id, starts_at in attended:
            key = _bucket_start(starts_at, bucket)
            active_by_bucket.setdefault(key, set()).add(discord_id)

        start_date = _bucket_start(start_moment, bucket)
        end_date = _bucket_start(now, bucket)
        step = timedelta(days=7) if bucket == "week" else timedelta(days=1)
        points: list[StatsTrendPoint] = []
        current = start_date
        while current <= end_date:
            points.append(
                StatsTrendPoint(
                    start=current,
                    messages=messages_by_bucket.get(current, 0),
                    voice_minutes=voice_by_bucket.get(current, 0),
                    active_members=len(active_by_bucket.get(current, set())),
                )
            )
            current += step
        return points

    @staticmethod
    def _build_heatmap(activity: list[MemberActivityHour]) -> list[StatsHourCell]:
        counts: dict[tuple[int, int], dict[str, int]] = {}
        for row in activity:
            local = row.hour_start.astimezone(GUILD_TZ)
            key = (local.weekday(), local.hour)
            entry = counts.setdefault(key, {"messages": 0, "voice_minutes": 0})
            entry["messages"] += row.messages
            entry["voice_minutes"] += row.voice_minutes
        cells = [
            StatsHourCell(
                weekday=weekday, hour=hour, messages=values["messages"], voice_minutes=values["voice_minutes"]
            )
            for (weekday, hour), values in counts.items()
            if values["messages"] or values["voice_minutes"]
        ]
        cells.sort(key=lambda cell: (cell.weekday, cell.hour))
        return cells

    # --- Gone quiet -----------------------------------------------------------------------------------------

    async def _last_activity_by_user(self) -> dict[int, datetime]:
        stmt = (
            select(MemberActivityHour.user_id, func.max(MemberActivityHour.hour_start))
            .where(
                MemberActivityHour.guild_id == self._guild_id,
                (MemberActivityHour.messages > 0) | (MemberActivityHour.voice_minutes > 0),
            )
            .group_by(MemberActivityHour.user_id)
        )
        return {int(user_id): last for user_id, last in (await self._session.execute(stmt)).all()}

    async def _last_attended_by_user(self, now: datetime) -> dict[int, datetime]:
        stmt = (
            select(Member.discord_id, func.max(GuildEvent.starts_at))
            .select_from(EventSignup)
            .join(GuildEvent, GuildEvent.id == EventSignup.event_id)
            .join(Member, Member.id == EventSignup.member_id)
            .where(attended_condition(now=now))
            .group_by(Member.discord_id)
        )
        return {int(discord_id): last for discord_id, last in (await self._session.execute(stmt)).all()}

    async def _levels_by_discord_id(self, discord_ids: list[int]) -> dict[int, int]:
        if not discord_ids:
            return {}
        stmt = select(MemberLevel.user_id, MemberLevel.level).where(
            MemberLevel.guild_id == self._guild_id, MemberLevel.user_id.in_(discord_ids)
        )
        return {int(user_id): level for user_id, level in (await self._session.execute(stmt)).all()}

    async def _gone_quiet(self, now: datetime) -> list[StatsQuietMember]:
        cutoff = now - timedelta(days=GONE_QUIET_DAYS)
        roster = list(
            (await self._session.execute(select(Member).where(Member.is_guild_member.is_(True)))).scalars().all()
        )
        last_activity = await self._last_activity_by_user()
        last_attended = await self._last_attended_by_user(now)
        levels = await self._levels_by_discord_id([member.discord_id for member in roster])

        quiet: list[tuple[datetime | None, Member]] = []
        for member in roster:
            candidates = [last_activity.get(member.discord_id), last_attended.get(member.discord_id)]
            last = max((c for c in candidates if c is not None), default=None)
            if last is not None and last >= cutoff:
                continue
            quiet.append((last, member))
        quiet.sort(key=lambda pair: (pair[0] is not None, pair[0]))

        return [
            StatsQuietMember(
                person=StatsPerson(
                    discord_id=str(member.discord_id),
                    display_name=member.display_name,
                    avatar_url=avatar_url(member.discord_id, member.avatar_hash),
                    member_id=member.id,
                ),
                last_active_at=last,
                level=levels.get(member.discord_id, 0),
            )
            for last, member in quiet[:GONE_QUIET_LIMIT]
        ]

    # --- Public read ------------------------------------------------------------------------------------------

    async def get_stats(self, stats_range: StatsRange, *, now: datetime | None = None) -> GuildStats:
        """Guild-wide activity stats for ``stats_range``."""
        reference = now or datetime.now(UTC)
        days = _RANGE_DAYS.get(stats_range)
        # Count back on the guild's wall clock, not in UTC hours: the trend's days are America/Chicago days, and
        # across a daylight-saving change 7 x 24 hours would land an hour off and drop or add a day.
        since = (reference.astimezone(GUILD_TZ) - timedelta(days=days)).astimezone(UTC) if days is not None else None
        bucket = "week" if stats_range in _WEEK_BUCKET_RANGES else "day"

        tracking_since = (
            await self._session.execute(
                select(func.min(MemberActivityHour.hour_start)).where(MemberActivityHour.guild_id == self._guild_id)
            )
        ).scalar_one_or_none()

        totals = await self._totals(since, None, reference)
        previous = None
        if since is not None and days is not None:
            previous_since = since - timedelta(days=days)
            previous = await self._totals(previous_since, since, reference)

        activity = await self._activity_rows(since, None)
        attended = await self._attended_rows(since, None, reference)
        groups = await self._counted_group_rows(since, None)
        grants = await self._xp_grant_rows(since, None)

        message_counts: dict[int, int] = {}
        voice_counts: dict[int, int] = {}
        xp_counts: dict[int, int] = {}
        for row in activity:
            if row.messages:
                message_counts[row.user_id] = message_counts.get(row.user_id, 0) + row.messages
            if row.voice_minutes:
                voice_counts[row.user_id] = voice_counts.get(row.user_id, 0) + row.voice_minutes
            earned = row.chat_xp + row.voice_xp
            if earned:
                xp_counts[row.user_id] = xp_counts.get(row.user_id, 0) + earned
        event_counts: dict[int, int] = {}
        for discord_id, _ in attended:
            event_counts[discord_id] = event_counts.get(discord_id, 0) + 1
        group_counts: dict[int, int] = {}
        for discord_id, _ in groups:
            group_counts[discord_id] = group_counts.get(discord_id, 0) + 1
        for discord_id, amount in grants:
            xp_counts[discord_id] = xp_counts.get(discord_id, 0) + amount

        all_ids = set(message_counts) | set(voice_counts) | set(event_counts) | set(group_counts) | set(xp_counts)
        people = await self._people(all_ids)

        return GuildStats(
            range=stats_range,
            since=since,
            tracking_since=tracking_since,
            totals=totals,
            previous=previous,
            trend_bucket=bucket,
            trend=self._build_trend(
                activity, attended, bucket, since=since, tracking_since=tracking_since, now=reference
            ),
            heatmap=self._build_heatmap(activity),
            top_chatters=self._top(message_counts, people),
            top_voice=self._top(voice_counts, people),
            top_events=self._top(event_counts, people),
            top_groups=self._top(group_counts, people),
            top_xp=self._top(xp_counts, people),
            gone_quiet=await self._gone_quiet(reference),
        )
