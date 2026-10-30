"""Hall of Heroes: a members-only leaderboard and per-member profile.

Not an ``advanced_alchemy`` repository service: it spans several tables (members, signups, events, levels,
badges, guild roles) rather than owning one, like ``GmService``. Attendance for raids/events/EP/attendance-rate is
defined once in ``sidequest_api.lib.attendance.attended_condition``; every stat here is derived from it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from litestar.exceptions import NotFoundException
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.lib.attendance import attended_condition
from sidequest_api.lib.discord import avatar_url
from sidequest_common.leveling import level_progress
from sidequest_common.models import EventSignup, GuildEvent, GuildRole, Member, MemberBadge, MemberLevel
from sidequest_common.schemas import (
    BADGES,
    EVENT_KIND_EP,
    SEASONS,
    EarnedBadge,
    HeroLeaderboard,
    HeroProfile,
    HeroRecentEvent,
    HeroRow,
    HeroSeasonStats,
    WowClass,
    event_ep,
)

if TYPE_CHECKING:
    from sidequest_common.schemas import Season
    from sidequest_common.settings import WebSettings

RECENT_EVENTS_LIMIT = 5
GUILD_TZ = ZoneInfo("America/Chicago")

_WOW_CLASSES = tuple(cls.value for cls in WowClass)

_EP_CASE = case(*[(GuildEvent.kind == kind.value, value) for kind, value in EVENT_KIND_EP.items()], else_=0)
_EP_EXPR = func.coalesce(GuildEvent.ep_override, _EP_CASE)


def _season_window(season: str, now: datetime) -> tuple[datetime | None, datetime | None, str, str]:
    """``(starts_at, ends_at, id, name)`` for a season id, ``"all"``, or ``"month"`` (the current calendar month)."""
    if season == "all":
        return None, None, "all", "All Time"
    if season == "month":
        local_now = now.astimezone(GUILD_TZ)
        month_start = datetime(local_now.year, local_now.month, 1, tzinfo=GUILD_TZ)
        return month_start.astimezone(UTC), None, "month", "This Month"
    for entry in SEASONS:
        if entry.id == season:
            return entry.starts_at, entry.ends_at, entry.id, entry.name
    msg = f"No season {season!r}"
    raise NotFoundException(msg)


def _current_season() -> Season:
    """The season with no end date: the one currently running."""
    return SEASONS[-1]


class HeroesService:
    """Reads behind the Hall of Heroes: the leaderboard and member profiles."""

    def __init__(self, session: AsyncSession, web_settings: WebSettings) -> None:
        self._session = session
        self._web_settings = web_settings

    # --- Stat aggregation ----------------------------------------------------------------------------------

    async def _attended_stats(
        self, *, since: datetime | None, until: datetime | None, now: datetime, member_ids: list[int] | None = None
    ) -> dict[int, dict[str, int]]:
        """``{member_id: {"ep", "raids", "events"}}`` over attended sign-ups in ``[since, until)``."""
        conditions = [attended_condition(now=now)]
        if since is not None:
            conditions.append(GuildEvent.starts_at >= since)
        if until is not None:
            conditions.append(GuildEvent.starts_at < until)
        if member_ids is not None:
            conditions.append(EventSignup.member_id.in_(member_ids))
        statement = (
            select(
                EventSignup.member_id,
                func.sum(_EP_EXPR).label("ep"),
                func.sum(case((GuildEvent.kind == "raid", 1), else_=0)).label("raids"),
                func.count().label("events"),
            )
            .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
            .where(*conditions)
            .group_by(EventSignup.member_id)
        )
        rows = (await self._session.execute(statement)).all()
        return {
            row.member_id: {"ep": int(row.ep or 0), "raids": int(row.raids), "events": int(row.events)} for row in rows
        }

    async def _signed_up_counts(
        self, *, since: datetime | None, until: datetime | None, now: datetime, member_ids: list[int] | None = None
    ) -> dict[int, int]:
        """Signups for completed (past, not cancelled) events in ``[since, until)``, the attendance-rate denominator."""
        conditions = [GuildEvent.starts_at < now, GuildEvent.status != "cancelled"]
        if since is not None:
            conditions.append(GuildEvent.starts_at >= since)
        if until is not None:
            conditions.append(GuildEvent.starts_at < until)
        if member_ids is not None:
            conditions.append(EventSignup.member_id.in_(member_ids))
        statement = (
            select(EventSignup.member_id, func.count())
            .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
            .where(*conditions)
            .group_by(EventSignup.member_id)
        )
        return dict((await self._session.execute(statement)).tuples().all())

    async def _season_stats(
        self, *, since: datetime | None, until: datetime | None, now: datetime, member_ids: list[int] | None = None
    ) -> dict[int, HeroSeasonStats]:
        attended = await self._attended_stats(since=since, until=until, now=now, member_ids=member_ids)
        signed_up = await self._signed_up_counts(since=since, until=until, now=now, member_ids=member_ids)
        stats: dict[int, HeroSeasonStats] = {}
        for member_id in set(attended) | set(signed_up):
            row = attended.get(member_id, {"ep": 0, "raids": 0, "events": 0})
            denom = signed_up.get(member_id, 0)
            rate = row["events"] / denom if denom > 0 else 0.0
            stats[member_id] = HeroSeasonStats(
                ep=row["ep"], raids_attended=row["raids"], events_attended=row["events"], attendance_rate=rate
            )
        return stats

    # --- Class ------------------------------------------------------------------------------------------------

    async def _signup_classes(self, member_ids: list[int] | None = None) -> dict[int, str]:
        """The class of each member's most recent signup that named one, newest event first."""
        statement = (
            select(EventSignup.member_id, EventSignup.wow_class)
            .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
            .where(EventSignup.wow_class.is_not(None))
            .order_by(GuildEvent.starts_at.desc())
        )
        if member_ids is not None:
            statement = statement.where(EventSignup.member_id.in_(member_ids))
        classes: dict[int, str] = {}
        for member_id, wow_class in (await self._session.execute(statement)).tuples().all():
            if wow_class is not None:
                classes.setdefault(member_id, wow_class)
        return classes

    async def _discord_role_classes(self, members: list[Member]) -> dict[int, str]:
        """Fallback class from a Discord role literally named after a class, for members with no signup class."""
        role_rows = (
            await self._session.execute(
                select(GuildRole.role_id, GuildRole.name).where(GuildRole.guild_id == self._web_settings.GUILD_ID)
            )
        ).all()
        role_id_by_class: dict[str, int] = {}
        for role_id, name in role_rows:
            lowered = name.strip().lower()
            if lowered in _WOW_CLASSES and lowered not in role_id_by_class:
                role_id_by_class[lowered] = role_id
        classes: dict[int, str] = {}
        for member in members:
            member_role_ids = set(member.roles)
            for wow_class in _WOW_CLASSES:
                role_id = role_id_by_class.get(wow_class)
                if role_id is not None and role_id in member_role_ids:
                    classes[member.id] = wow_class
                    break
        return classes

    async def _classes_for(self, members: list[Member]) -> dict[int, str | None]:
        member_ids = [member.id for member in members]
        signup_classes = await self._signup_classes(member_ids)
        missing = [member for member in members if member.id not in signup_classes]
        role_classes = await self._discord_role_classes(missing) if missing else {}
        return {member.id: signup_classes.get(member.id) or role_classes.get(member.id) for member in members}

    # --- Badges -------------------------------------------------------------------------------------------

    async def _badges_for(self, member_id: int) -> list[EarnedBadge]:
        statement = select(MemberBadge).where(MemberBadge.member_id == member_id).order_by(MemberBadge.earned_at.desc())
        rows = (await self._session.execute(statement)).scalars().all()
        badges: list[EarnedBadge] = []
        for row in rows:
            definition = BADGES.get(row.badge_id)
            if definition is None:
                continue
            badges.append(
                EarnedBadge(
                    id=definition.id,
                    name=definition.name,
                    description=definition.description,
                    icon=definition.icon,
                    earned_at=row.earned_at,
                )
            )
        return badges

    async def _badge_ids_by_member(self, member_ids: list[int]) -> dict[int, list[str]]:
        if not member_ids:
            return {}
        statement = select(MemberBadge.member_id, MemberBadge.badge_id).where(MemberBadge.member_id.in_(member_ids))
        badge_ids: dict[int, list[str]] = {}
        for member_id, badge_id in (await self._session.execute(statement)).tuples().all():
            badge_ids.setdefault(member_id, []).append(badge_id)
        return badge_ids

    # --- Chat level -----------------------------------------------------------------------------------------

    async def _levels_by_member(self, members: list[Member]) -> dict[int, MemberLevel]:
        discord_ids = [member.discord_id for member in members]
        if not discord_ids:
            return {}
        statement = select(MemberLevel).where(
            MemberLevel.guild_id == self._web_settings.GUILD_ID, MemberLevel.user_id.in_(discord_ids)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        by_discord = {level.user_id: level for level in rows}
        return {member.id: by_discord[member.discord_id] for member in members if member.discord_id in by_discord}

    # --- Public reads -----------------------------------------------------------------------------------------

    async def get_leaderboard(self, season: str, *, now: datetime | None = None) -> HeroLeaderboard:
        """Everyone on the roster, holding a badge or with EP in the season (an id, ``"all"``, or ``"month"``).

        Highest EP first, then raids, then name. Only members with EP this season get a ``rank``.
        """
        reference = now or datetime.now(UTC)
        since, until, season_id, season_name = _season_window(season, reference)
        stats = await self._season_stats(since=since, until=until, now=reference)
        listed = select(Member).where(
            or_(
                Member.id.in_([member_id for member_id, stat in stats.items() if stat.ep > 0]),
                and_(Member.is_guild_member.is_(True), Member.roster_confirmed_at.is_not(None)),
                Member.id.in_(select(MemberBadge.member_id)),
            )
        )
        members = list((await self._session.execute(listed)).scalars())
        if not members:
            return HeroLeaderboard(season_id=season_id, season_name=season_name, rows=[])
        member_ids = [member.id for member in members]
        members_by_id = {member.id: member for member in members}
        classes = await self._classes_for(members)
        levels = await self._levels_by_member(members)
        badge_ids = await self._badge_ids_by_member(member_ids)
        zero_stats = HeroSeasonStats(ep=0, raids_attended=0, events_attended=0, attendance_rate=0.0)
        ordered = sorted(
            member_ids,
            key=lambda mid: (
                -stats.get(mid, zero_stats).ep,
                -stats.get(mid, zero_stats).raids_attended,
                members_by_id[mid].display_name.casefold(),
                mid,
            ),
        )
        rows = []
        for position, member_id in enumerate(ordered, start=1):
            member = members_by_id[member_id]
            stat = stats.get(member_id, zero_stats)
            level = levels.get(member_id)
            rows.append(
                HeroRow(
                    rank=position if stat.ep > 0 else None,
                    member_id=member_id,
                    discord_id=str(member.discord_id),
                    display_name=member.display_name,
                    avatar_url=avatar_url(member.discord_id, member.avatar_hash),
                    wow_class=classes.get(member_id),
                    chat_level=level.level if level else 0,
                    ep=stat.ep,
                    raids_attended=stat.raids_attended,
                    events_attended=stat.events_attended,
                    badge_ids=sorted(badge_ids.get(member_id, [])),
                )
            )
        return HeroLeaderboard(season_id=season_id, season_name=season_name, rows=rows)

    async def get_profile(self, member_id: int, *, now: datetime | None = None) -> HeroProfile:
        """A member's full profile: per-season and all-time stats, rank, chat level, recent events, badges."""
        member = await self._session.get(Member, member_id)
        if member is None:
            msg = f"No member {member_id}"
            raise NotFoundException(msg)
        reference = now or datetime.now(UTC)

        seasons: dict[str, HeroSeasonStats] = {}
        rank: int | None = None
        zero_stats = HeroSeasonStats(ep=0, raids_attended=0, events_attended=0, attendance_rate=0.0)
        for entry in SEASONS:
            stats = await self._season_stats(since=entry.starts_at, until=entry.ends_at, now=reference)
            seasons[entry.id] = stats.get(member_id, zero_stats)

        current = _current_season()
        leaderboard = await self.get_leaderboard(current.id, now=reference)
        for row in leaderboard.rows:
            if row.member_id == member_id:
                rank = row.rank
                break

        all_time_stats = await self._season_stats(since=None, until=None, now=reference)
        all_time = all_time_stats.get(member_id, zero_stats)

        classes = await self._classes_for([member])
        levels = await self._levels_by_member([member])
        level = levels.get(member_id)
        progress = level_progress(level.xp) if level else level_progress(0)

        first_event_row = (
            await self._session.execute(
                select(func.min(GuildEvent.starts_at))
                .join(EventSignup, EventSignup.event_id == GuildEvent.id)
                .where(EventSignup.member_id == member_id, attended_condition(now=reference))
            )
        ).scalar_one_or_none()
        first_event_date = first_event_row.astimezone(GUILD_TZ).date() if first_event_row is not None else None

        recent_rows = (
            (
                await self._session.execute(
                    select(GuildEvent)
                    .join(EventSignup, EventSignup.event_id == GuildEvent.id)
                    .where(EventSignup.member_id == member_id, attended_condition(now=reference))
                    .order_by(GuildEvent.starts_at.desc())
                    .limit(RECENT_EVENTS_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        recent_events = [
            HeroRecentEvent(
                id=event.id,
                kind=event.kind,
                title=event.title,
                starts_at=event.starts_at,
                ep=event_ep(event.kind, event.ep_override),
            )
            for event in recent_rows
        ]

        badges = await self._badges_for(member_id)

        return HeroProfile(
            member_id=member.id,
            discord_id=str(member.discord_id),
            display_name=member.display_name,
            avatar_url=avatar_url(member.discord_id, member.avatar_hash),
            wow_class=classes.get(member_id),
            rank=rank,
            chat_level=level.level if level else 0,
            chat_xp=level.xp if level else 0,
            chat_xp_into_level=progress.xp_into_level,
            chat_xp_for_next_level=progress.xp_for_next_level,
            seasons=seasons,
            all_time=all_time,
            first_event_date=first_event_date,
            recent_events=recent_events,
            badges=badges,
        )
