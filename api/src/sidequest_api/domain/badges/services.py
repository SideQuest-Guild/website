"""Hall of Heroes badge awarding: computed server-side from attendance, levels, and the roster.

Not an ``advanced_alchemy`` repository service: it spans several tables, like ``HeroesService``/``GmService``.
Awarding is idempotent (safe to run on every bot poll): permanent badges are inserted once and never removed;
``top_helper`` is a moving monthly title, re-pointed to a new member when last month's winner changes, and left
alone when nobody attended a dungeon/leveling event last month (no new achiever to replace the current holder).
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.lib.attendance import attended_condition
from sidequest_common.models import EventSignup, GuildEvent, Member, MemberBadge, MemberLevel
from sidequest_common.schemas import BADGES, BadgeRoleState, PendingBadgeAnnouncement
from sidequest_common.schemas.badges import (
    CHATTERBOX_LEVEL,
    FOUNDING_MEMBER_CUTOFF_ISO,
    PERFECT_MONTH_MIN_RAIDS,
    RAID_REGULAR_THRESHOLD,
    RAID_VETERAN_THRESHOLD,
)

GUILD_TZ = ZoneInfo("America/Chicago")
FOUNDING_MEMBER_CUTOFF = datetime.fromisoformat(FOUNDING_MEMBER_CUTOFF_ISO)
DECEMBER = 12
JANUARY = 1
_DUNGEON_LEVELING_KINDS = ("dungeon", "leveling")


def _month_key(when: datetime) -> tuple[int, int]:
    local = when.astimezone(GUILD_TZ)
    return local.year, local.month


def _current_month_start(now: datetime) -> datetime:
    """The UTC instant of midnight on the 1st of ``now``'s calendar month in America/Chicago."""
    local = now.astimezone(GUILD_TZ)
    month_start_local = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return month_start_local.astimezone(UTC)


def _previous_month(now: datetime) -> tuple[int, int]:
    local = now.astimezone(GUILD_TZ)
    if local.month == JANUARY:
        return local.year - 1, DECEMBER
    return local.year, local.month - 1


class BadgeService:
    """Computes who's earned which badge, awards new ones, and reports what the bot should do about it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _guild_members(self) -> list[Member]:
        statement = select(Member).where(Member.is_guild_member.is_(True))
        return list((await self._session.execute(statement)).scalars().all())

    async def _attendance_counts(self, member_ids: list[int], *, now: datetime) -> dict[int, dict[str, int]]:
        """``{member_id: {"events", "raids"}}`` all-time attended counts."""
        if not member_ids:
            return {}
        statement = (
            select(EventSignup.member_id, GuildEvent.kind)
            .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
            .where(EventSignup.member_id.in_(member_ids), attended_condition(now=now))
        )
        counts: dict[int, dict[str, int]] = {}
        for member_id, kind in (await self._session.execute(statement)).tuples().all():
            row = counts.setdefault(member_id, {"events": 0, "raids": 0})
            row["events"] += 1
            if kind == "raid":
                row["raids"] += 1
        return counts

    async def _perfect_month_members(self, member_ids: list[int], *, now: datetime) -> set[int]:
        """Members who, in some completed America/Chicago calendar month, attended every raid run that month.

        The current, still-in-progress Chicago month is excluded: it isn't known yet whether more raids remain,
        so awarding this permanent badge from a partial month could award it to someone who goes on to miss the
        rest of the month's raids.
        """
        if not member_ids:
            return set()
        month_boundary = _current_month_start(now)
        statement = select(GuildEvent.id, GuildEvent.starts_at).where(
            GuildEvent.kind == "raid", GuildEvent.status != "cancelled", GuildEvent.starts_at < month_boundary
        )
        raid_rows = (await self._session.execute(statement)).tuples().all()
        raids_per_month: dict[tuple[int, int], set] = {}
        for event_id, starts_at in raid_rows:
            raids_per_month.setdefault(_month_key(starts_at), set()).add(event_id)
        if not raids_per_month:
            return set()

        statement = (
            select(EventSignup.member_id, GuildEvent.id, GuildEvent.starts_at)
            .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
            .where(
                EventSignup.member_id.in_(member_ids),
                GuildEvent.kind == "raid",
                GuildEvent.starts_at < month_boundary,
                attended_condition(now=now),
            )
        )
        attended_per_member_month: dict[int, dict[tuple[int, int], set]] = {}
        for member_id, event_id, starts_at in (await self._session.execute(statement)).tuples().all():
            member_months = attended_per_member_month.setdefault(member_id, {})
            member_months.setdefault(_month_key(starts_at), set()).add(event_id)

        perfect: set[int] = set()
        for member_id, months in attended_per_member_month.items():
            for month, attended_ids in months.items():
                total_ids = raids_per_month.get(month, set())
                if len(total_ids) >= PERFECT_MONTH_MIN_RAIDS and attended_ids >= total_ids:
                    perfect.add(member_id)
                    break
        return perfect

    async def _top_helper_winner(self, member_ids: list[int], *, now: datetime) -> int | None:
        """The member with the most dungeon/leveling events attended last calendar month, or ``None``."""
        if not member_ids:
            return None
        year, month = _previous_month(now)
        start = datetime(year, month, 1, tzinfo=GUILD_TZ).astimezone(UTC)
        end_year, end_month = (year + 1, 1) if month == DECEMBER else (year, month + 1)
        end = datetime(end_year, end_month, 1, tzinfo=GUILD_TZ).astimezone(UTC)
        statement = (
            select(EventSignup.member_id, GuildEvent.id)
            .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
            .where(
                EventSignup.member_id.in_(member_ids),
                GuildEvent.kind.in_(_DUNGEON_LEVELING_KINDS),
                GuildEvent.starts_at >= start,
                GuildEvent.starts_at < end,
                attended_condition(now=now),
            )
        )
        counts: dict[int, int] = {}
        for member_id, _event_id in (await self._session.execute(statement)).tuples().all():
            counts[member_id] = counts.get(member_id, 0) + 1
        if not counts:
            return None
        best = max(counts.values())
        winners = sorted(member_id for member_id, count in counts.items() if count == best)
        return winners[0]

    async def _award_permanent(self, member_id: int, badge_id: str, *, now: datetime) -> None:
        existing = (
            await self._session.execute(
                select(MemberBadge).where(MemberBadge.member_id == member_id, MemberBadge.badge_id == badge_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        self._session.add(MemberBadge(member_id=member_id, badge_id=badge_id, earned_at=now, announced_at=None))

    async def _sync_top_helper(self, winner: int | None, *, now: datetime) -> None:
        existing = (
            await self._session.execute(select(MemberBadge).where(MemberBadge.badge_id == "top_helper"))
        ).scalar_one_or_none()
        if winner is None:
            return
        if existing is not None and existing.member_id == winner:
            return
        if existing is not None:
            await self._session.delete(existing)
            await self._session.flush()
        self._session.add(MemberBadge(member_id=winner, badge_id="top_helper", earned_at=now, announced_at=None))

    async def sync(
        self, *, guild_id: int, now: datetime | None = None
    ) -> tuple[list[BadgeRoleState], list[PendingBadgeAnnouncement]]:
        """Recompute and award every badge for current guild members, then report role state and new announcements."""
        reference = now or datetime.now(UTC)
        members = await self._guild_members()
        member_ids = [member.id for member in members]

        attendance = await self._attendance_counts(member_ids, now=reference)
        perfect_month_members = await self._perfect_month_members(member_ids, now=reference)
        top_helper_winner = await self._top_helper_winner(member_ids, now=reference)

        level_rows = (
            (
                await self._session.execute(
                    select(MemberLevel.user_id, MemberLevel.level).where(MemberLevel.guild_id == guild_id)
                )
            )
            .tuples()
            .all()
        )
        level_by_discord_id = dict(level_rows)

        for member in members:
            counts = attendance.get(member.id, {"events": 0, "raids": 0})
            if counts["events"] >= 1:
                await self._award_permanent(member.id, "first_steps", now=reference)
            if counts["raids"] >= 1:
                await self._award_permanent(member.id, "first_raid", now=reference)
            if counts["raids"] >= RAID_REGULAR_THRESHOLD:
                await self._award_permanent(member.id, "raid_regular", now=reference)
            if counts["raids"] >= RAID_VETERAN_THRESHOLD:
                await self._award_permanent(member.id, "raid_veteran", now=reference)
            if member.id in perfect_month_members:
                await self._award_permanent(member.id, "perfect_month", now=reference)
            if member.roster_confirmed_at is not None and member.roster_confirmed_at < FOUNDING_MEMBER_CUTOFF:
                await self._award_permanent(member.id, "founding_member", now=reference)
            if level_by_discord_id.get(member.discord_id, 0) >= CHATTERBOX_LEVEL:
                await self._award_permanent(member.id, "chatterbox", now=reference)

        await self._sync_top_helper(top_helper_winner, now=reference)
        await self._session.commit()

        badge_rows = (
            (await self._session.execute(select(MemberBadge).where(MemberBadge.member_id.in_(member_ids))))
            .scalars()
            .all()
        )
        badges_by_member: dict[int, list[str]] = {}
        pending: list[PendingBadgeAnnouncement] = []
        members_by_id = {member.id: member for member in members}
        for row in badge_rows:
            badges_by_member.setdefault(row.member_id, []).append(row.badge_id)
            if row.announced_at is None:
                definition = BADGES.get(row.badge_id)
                if definition is not None:
                    pending.append(
                        PendingBadgeAnnouncement(
                            discord_id=members_by_id[row.member_id].discord_id,
                            badge_id=definition.id,
                            name=definition.name,
                            description=definition.description,
                        )
                    )

        role_state = [
            BadgeRoleState(discord_id=member.discord_id, badge_ids=sorted(badges_by_member.get(member.id, [])))
            for member in members
        ]
        return role_state, pending

    async def ack(self, discord_id: int, badge_id: str) -> None:
        """Mark one member's badge as announced; no-op if the member or the badge row doesn't exist."""
        member = (
            await self._session.execute(select(Member).where(Member.discord_id == discord_id))
        ).scalar_one_or_none()
        if member is None:
            return
        row = (
            await self._session.execute(
                select(MemberBadge).where(MemberBadge.member_id == member.id, MemberBadge.badge_id == badge_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return
        row.announced_at = datetime.now(UTC)
        await self._session.commit()
