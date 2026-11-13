"""Recruitment drive qualification engine: who invited whom, and whether each recruit has qualified for payout.

See ``local://recruitment-contract.md``. ``evaluate`` is the single place that writes ``RecruitmentRecruit`` rows,
and is idempotent: it runs after an addon export import (``EpgpService.import_payload``), at the end of the
Battle.net roster sync (``CharactersService.sync_roster``), and before serving the drive/payout reads below.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003 - pydantic/SQLAlchemy need it at runtime

from litestar.exceptions import NotFoundException
from sqlalchemy import and_, func, or_, select

from sidequest_common.models import (
    BattlenetCharacter,
    GuildEvent,
    GuildLogEntry,
    GuildRosterSnapshot,
    Member,
    RecruitmentRecruit,
    WowCharacter,
)
from sidequest_common.schemas import (
    DRIVE_PRIZE_COPPER,
    DRIVE_SETTLE_DAYS,
    RECRUIT_JOIN_WINDOW,
    RECRUIT_MIN_LEVEL,
    RECRUIT_STAY_DAYS,
    DriveRecruit,
    DriveRecruitReason,
    DriveRecruitStatus,
    EventKind,
    PaidVia,
    RecruitLeader,
    RecruitmentDrive,
    RecruitmentDriveTotals,
    RecruitPayout,
    character_key,
)


def winning_groups(rows: Sequence[RecruitmentRecruit]) -> dict[str, list[RecruitmentRecruit]]:
    """Qualified recruit rows grouped by inviter, kept only for the inviter(s) tied for the most.

    The drive's prize goes to whoever has the most qualifying recruits; ties each win, each winner getting the full
    prize. Empty if ``rows`` is empty (no qualified recruits: no winner).
    """
    by_inviter: dict[str, list[RecruitmentRecruit]] = {}
    for row in rows:
        by_inviter.setdefault(row.inviter_name, []).append(row)
    if not by_inviter:
        return {}
    max_count = max(len(group) for group in by_inviter.values())
    return {inviter: group for inviter, group in by_inviter.items() if len(group) == max_count}


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


def _name_variants(name: str) -> set[str]:
    """A name and (if it has a surname) its bare first-name alias.

    ``GetGuildEventInfo`` is not confirmed to always carry the surname the way the roster does; matching against
    either form lets a resolved ``First-Surname`` identity still match guild-log rows recorded with just the bare
    first name (WoW character names are unique on a realm, so the bare form is unambiguous).
    """
    stripped = name.strip().lower()
    variants = {stripped}
    if "-" in stripped:
        variants.add(stripped.split("-", 1)[0])
    return variants


async def build_leaders(session: AsyncSession, rows: Sequence[RecruitmentRecruit]) -> list[RecruitLeader]:
    """``RecruitLeader`` rows for one drive's recruits, sorted qualified desc, joined desc, invited desc, inviter asc.

    Shared by ``RecruitmentService.get_drive`` and the event-sync forum-thread tally so both leaderboards agree.
    """
    by_inviter: dict[str, list[RecruitmentRecruit]] = {}
    for row in rows:
        by_inviter.setdefault(row.inviter_name, []).append(row)
    leaders = []
    for inviter, group in by_inviter.items():
        member_name = discord_id = None
        character_id = next((row.inviter_character_id for row in group if row.inviter_character_id is not None), None)
        if character_id is not None:
            char = await session.get(WowCharacter, character_id)
            if char is not None and char.member_id is not None:
                member = await session.get(Member, char.member_id)
                if member is not None:
                    member_name = member.display_name
                    discord_id = str(member.discord_id)
        leaders.append(
            RecruitLeader(
                inviter=inviter,
                member_name=member_name,
                discord_id=discord_id,
                invited=len(group),
                joined=sum(1 for row in group if row.joined_at is not None),
                counting=sum(1 for row in group if row.status == "counting"),
                qualified=sum(1 for row in group if row.status == "qualified"),
            )
        )
    leaders.sort(key=lambda leader: (-leader.qualified, -leader.joined, -leader.invited, leader.inviter))
    return leaders


class RecruitmentService:
    """Recomputes drive qualification state, and serves the drive/payout reads."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """The request's session, for callers (e.g. the payouts-paid officer audit write) that need it directly."""
        return self._session

    # --- Evaluation ---------------------------------------------------------------------------------------------

    async def evaluate(self, now: datetime | None = None) -> None:
        """Recompute every started recruitment drive's recruit rows against the guild log and roster. Idempotent."""
        now = now or datetime.now(UTC)
        drives = (
            (
                await self._session.execute(
                    select(GuildEvent).where(
                        GuildEvent.kind == EventKind.RECRUITMENT.value,
                        GuildEvent.starts_at <= now,
                        GuildEvent.ends_at.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for drive in drives:
            await self._evaluate_drive(drive, now)
        await self._session.commit()

    async def _evaluate_drive(self, drive: GuildEvent, now: datetime) -> None:
        ends_at = drive.ends_at
        if ends_at is None:
            return
        invites = (
            (
                await self._session.execute(
                    select(GuildLogEntry)
                    .where(
                        GuildLogEntry.kind == "invite",
                        GuildLogEntry.at >= drive.starts_at,
                        GuildLogEntry.at <= ends_at,
                        GuildLogEntry.target.is_not(None),
                    )
                    .order_by(GuildLogEntry.at.asc())
                )
            )
            .scalars()
            .all()
        )
        name_cache: dict[str, str] = {}
        latest_invite_by_recruit: dict[str, tuple[datetime, str]] = {}
        for invite in invites:
            if invite.target is None:
                continue
            recruit_name = await self._resolve_name(invite.target, name_cache)
            inviter_name = await self._resolve_name(invite.actor, name_cache)
            latest_invite_by_recruit[recruit_name] = (invite.at, inviter_name)

        existing_rows = {
            row.recruit_name: row
            for row in (
                await self._session.execute(select(RecruitmentRecruit).where(RecruitmentRecruit.event_id == drive.id))
            )
            .scalars()
            .all()
        }

        for recruit_name, (invited_at, inviter_name) in latest_invite_by_recruit.items():
            existing = existing_rows.get(recruit_name)
            if existing is not None and existing.paid_at is not None:
                continue  # frozen forever once paid: never un-qualify a paid row
            row = existing or RecruitmentRecruit(event_id=drive.id, recruit_name=recruit_name)
            if existing is None:
                self._session.add(row)
            # Latest invite wins, unless the row already qualified (a re-invite there would wipe its join clock);
            # a re-invite on a disqualified/invited/counting row starts a brand-new 7-day count.
            already_qualified = existing is not None and existing.status == "qualified"
            if not already_qualified and (row.invited_at != invited_at or row.inviter_name != inviter_name):
                row.invited_at = invited_at
                row.inviter_name = inviter_name
                row.joined_at = None
                row.qualifies_at = None
                row.status = "invited"
                row.reason = None
                row.qualified_at = None
            row.recruit_character_id = await self._match_character(row.recruit_name)
            row.inviter_character_id = await self._match_character(row.inviter_name)
            if already_qualified:
                # Everything else about a qualified row is settled; only a member linking an alt after the fact
                # (own_alt) can still change its outcome, and only until it's paid.
                await self._recheck_own_alt(row)
            else:
                await self._evaluate_recruit(drive, row, now)
        await self._session.flush()

    async def _resolve_name(self, name: str, cache: dict[str, str]) -> str:
        """A surname-less guild-log name resolved to its unique ``First-Surname`` identity.

        ``GetGuildEventInfo`` is not confirmed to give ``First-Surname`` the way the roster does; a bare name is
        resolved to the single ``BattlenetCharacter`` whose name casefolds to it (in-roster preferred), and left
        unchanged if that's ambiguous (0 or 2+ matches). Cached per ``evaluate()`` call.
        """
        stripped = name.strip()
        if "-" in stripped:
            return stripped
        if stripped in cache:
            return cache[stripped]
        name_lower = stripped.lower()
        matches = (
            await self._session.execute(
                select(BattlenetCharacter.name, BattlenetCharacter.surname, BattlenetCharacter.in_roster).where(
                    func.lower(BattlenetCharacter.name) == name_lower
                )
            )
        ).all()
        in_roster_matches = [match for match in matches if match.in_roster]
        candidates = in_roster_matches or matches
        resolved = f"{candidates[0].name}-{candidates[0].surname}" if len(candidates) == 1 else stripped
        cache[stripped] = resolved
        return resolved

    async def _match_character(self, name: str) -> UUID | None:
        key = character_key(name)
        statement = select(WowCharacter.id).where(WowCharacter.key == key)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def _is_own_alt(self, row: RecruitmentRecruit) -> bool:
        if row.recruit_character_id is None or row.inviter_character_id is None:
            return False
        recruit_member = (
            await self._session.execute(
                select(WowCharacter.member_id).where(WowCharacter.id == row.recruit_character_id)
            )
        ).scalar_one_or_none()
        inviter_member = (
            await self._session.execute(
                select(WowCharacter.member_id).where(WowCharacter.id == row.inviter_character_id)
            )
        ).scalar_one_or_none()
        return recruit_member is not None and recruit_member == inviter_member

    async def _recheck_own_alt(self, row: RecruitmentRecruit) -> None:
        if await self._is_own_alt(row):
            row.status, row.reason = "disqualified", "own_alt"

    async def _evaluate_recruit(self, drive: GuildEvent, row: RecruitmentRecruit, now: datetime) -> None:
        if await self._was_returning(row.recruit_name, drive.starts_at):
            row.status, row.reason = "disqualified", "returning"
            return
        if await self._is_own_alt(row):
            row.status, row.reason = "disqualified", "own_alt"
            return
        if row.joined_at is None:
            join = await self._find_join(row.recruit_name, row.invited_at)
            if join is not None:
                row.joined_at = join.at
                row.qualifies_at = join.at + timedelta(days=RECRUIT_STAY_DAYS)
            elif now - row.invited_at >= RECRUIT_JOIN_WINDOW:
                row.status, row.reason = "disqualified", "never_joined"
                return
            else:
                row.status = "invited"
                return
        if await self._has_left(row, now):
            row.status, row.reason = "disqualified", "left"
            return
        if row.qualifies_at is None or now < row.qualifies_at:
            row.status = "counting"
            return
        level = await self._current_level(row.recruit_name, row.recruit_character_id)
        row.level = level
        if level is None:
            # Unknown, not low: wait for a later roster sync to settle it rather than disqualifying on no data.
            row.status, row.reason = "counting", None
        elif level >= RECRUIT_MIN_LEVEL:
            row.status, row.reason = "qualified", None
            row.qualified_at = row.qualified_at or now
        else:
            row.status, row.reason = "disqualified", "low_level"

    async def _was_returning(self, recruit_name: str, starts_at: datetime) -> bool:
        """Already in the guild before the drive started.

        An earlier guild-log join (as this person) or invite (targeting this person) before ``starts_at``, a
        Battle.net roster row that joined before ``starts_at`` (or was already in the roster at the very first
        sync), or an addon roster snapshot recorded before ``starts_at``.
        """
        variants = _name_variants(recruit_name)
        earlier_log = (
            await self._session.execute(
                select(GuildLogEntry.id)
                .where(
                    or_(
                        and_(GuildLogEntry.kind == "join", func.lower(GuildLogEntry.actor).in_(variants)),
                        and_(GuildLogEntry.kind == "invite", func.lower(GuildLogEntry.target).in_(variants)),
                    ),
                    GuildLogEntry.at < starts_at,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if earlier_log is not None:
            return True
        key = character_key(recruit_name)
        battlenet = (
            await self._session.execute(select(BattlenetCharacter).where(BattlenetCharacter.slug == key))
        ).scalar_one_or_none()
        if battlenet is not None:
            if battlenet.joined_roster_at is not None and battlenet.joined_roster_at < starts_at:
                return True
            # joined_roster_at is only ever set on a non-first sync; null means this row was already in_roster
            # the first time we ever synced the roster, so "before starts_at" is the row's own creation time.
            if battlenet.joined_roster_at is None and battlenet.created_at < starts_at:
                return True
        char_id = (
            await self._session.execute(select(WowCharacter.id).where(WowCharacter.key == key))
        ).scalar_one_or_none()
        if char_id is not None:
            snapshot_created = (
                await self._session.execute(
                    select(GuildRosterSnapshot.created_at).where(GuildRosterSnapshot.character_id == char_id)
                )
            ).scalar_one_or_none()
            if snapshot_created is not None and snapshot_created < starts_at:
                return True
        return False

    async def _find_join(self, recruit_name: str, invited_at: datetime) -> GuildLogEntry | None:
        """The recruit's join, within the join window after the invite.

        Both timestamps are rounded down to the hour by the game's log, so a join logged up to an hour before the
        invite still pairs with it.
        """
        variants = _name_variants(recruit_name)
        return (
            (
                await self._session.execute(
                    select(GuildLogEntry)
                    .where(
                        GuildLogEntry.kind == "join",
                        func.lower(GuildLogEntry.actor).in_(variants),
                        GuildLogEntry.at >= invited_at - timedelta(hours=1),
                        GuildLogEntry.at <= invited_at + RECRUIT_JOIN_WINDOW,
                    )
                    .order_by(GuildLogEntry.at.asc())
                )
            )
            .scalars()
            .first()
        )

    async def _has_left(self, row: RecruitmentRecruit, now: datetime) -> bool:
        """True if the recruit left during their 7 days, or has none the moment the 7 days are up.

        A quit/remove guild-log entry or Battle.net showing them leaving in that window counts; once the 7 days
        are up, simply not being in the guild any more counts too.
        """
        joined_at, qualifies_at = row.joined_at, row.qualifies_at
        if joined_at is None or qualifies_at is None:
            return False
        variants = _name_variants(row.recruit_name)
        log_departure = (
            await self._session.execute(
                select(GuildLogEntry.id).where(
                    or_(
                        and_(GuildLogEntry.kind == "quit", func.lower(GuildLogEntry.actor).in_(variants)),
                        and_(GuildLogEntry.kind == "remove", func.lower(GuildLogEntry.target).in_(variants)),
                    ),
                    GuildLogEntry.at >= joined_at,
                    GuildLogEntry.at < qualifies_at,
                )
            )
        ).scalar_one_or_none()
        if log_departure is not None:
            return True
        key = character_key(row.recruit_name)
        battlenet = (
            await self._session.execute(select(BattlenetCharacter).where(BattlenetCharacter.slug == key))
        ).scalar_one_or_none()
        if battlenet is None:
            return False
        if battlenet.left_roster_at is not None and joined_at <= battlenet.left_roster_at < qualifies_at:
            return True
        return now >= qualifies_at and not battlenet.in_roster

    async def _current_level(self, recruit_name: str, character_id: UUID | None) -> int | None:
        """The highest level the addon roster or Battle.net's roster knows for this recruit, or None.

        Battle.net's row is found by name (its slug is the same ``first-surname`` key), so a recruit only the
        Battle.net roster sync has seen still gets a level.
        """
        levels: list[int] = []
        if character_id is not None:
            snapshot_level = (
                await self._session.execute(
                    select(GuildRosterSnapshot.level).where(GuildRosterSnapshot.character_id == character_id)
                )
            ).scalar_one_or_none()
            if snapshot_level is not None:
                levels.append(snapshot_level)
        battlenet_level = (
            await self._session.execute(
                select(BattlenetCharacter.level).where(BattlenetCharacter.slug == character_key(recruit_name))
            )
        ).scalar_one_or_none()
        if battlenet_level is not None:
            levels.append(battlenet_level)
        return max(levels) if levels else None

    # --- Reads ---------------------------------------------------------------------------------------------------

    async def get_drive(self, event_id: UUID) -> RecruitmentDrive:
        """The drive's full detail, leaderboard, and recruit rows, freshly evaluated. 404 if not a recruitment drive."""
        await self.evaluate()
        drive = await self._session.get(GuildEvent, event_id)
        if drive is None or drive.kind != EventKind.RECRUITMENT.value or drive.ends_at is None:
            msg = f"No recruitment drive {event_id}"
            raise NotFoundException(msg)
        rows = (
            (await self._session.execute(select(RecruitmentRecruit).where(RecruitmentRecruit.event_id == event_id)))
            .scalars()
            .all()
        )
        settles_at = drive.ends_at + timedelta(days=DRIVE_SETTLE_DAYS)
        totals = RecruitmentDriveTotals(
            invited=len(rows),
            joined=sum(1 for row in rows if row.joined_at is not None),
            counting=sum(1 for row in rows if row.status == "counting"),
            qualified=sum(1 for row in rows if row.status == "qualified"),
            disqualified=sum(1 for row in rows if row.status == "disqualified"),
            paid=sum(1 for row in rows if row.paid_at is not None),
        )
        leaders = await build_leaders(self._session, rows)
        recruits = [
            DriveRecruit(
                recruit=row.recruit_name,
                inviter=row.inviter_name,
                invited_at=row.invited_at,
                joined_at=row.joined_at,
                qualifies_at=row.qualifies_at,
                status=DriveRecruitStatus(row.status),
                reason=DriveRecruitReason(row.reason) if row.reason else None,
                paid_at=row.paid_at,
            )
            for row in rows
        ]
        return RecruitmentDrive(
            event_id=drive.id,
            title=drive.title,
            starts_at=drive.starts_at,
            ends_at=drive.ends_at,
            settles_at=settles_at,
            reward_copper=DRIVE_PRIZE_COPPER,
            min_level=RECRUIT_MIN_LEVEL,
            stay_days=RECRUIT_STAY_DAYS,
            totals=totals,
            leaders=leaders,
            recruits=recruits,
        )

    async def list_payouts(self, now: datetime | None = None) -> list[RecruitPayout]:
        """Settled drives' winner(s) (most qualifying recruits, ties each win), unpaid first.

        A winner is "paid" once any of their qualified rows in the drive is paid (``mark_paid``/the addon import
        stamp every qualified unpaid row for a winner at once), so a recruit who qualifies later never produces a
        second payout for an already-paid winner.
        """
        await self.evaluate(now)
        now = now or datetime.now(UTC)
        drives = (
            (
                await self._session.execute(
                    select(GuildEvent).where(
                        GuildEvent.kind == EventKind.RECRUITMENT.value, GuildEvent.ends_at.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        payouts: list[RecruitPayout] = []
        for drive in drives:
            if drive.ends_at is None:
                continue
            settles_at = drive.ends_at + timedelta(days=DRIVE_SETTLE_DAYS)
            if settles_at > now:
                continue
            rows = (
                (
                    await self._session.execute(
                        select(RecruitmentRecruit).where(
                            RecruitmentRecruit.event_id == drive.id, RecruitmentRecruit.status == "qualified"
                        )
                    )
                )
                .scalars()
                .all()
            )
            for inviter, group in winning_groups(rows).items():
                paid_group = [row for row in group if row.paid_at is not None]
                if paid_group:
                    last = max(paid_group, key=lambda row: row.paid_at)  # type: ignore[arg-type,return-value]
                    paid_at, paid_by = last.paid_at, last.paid_by
                    paid_via = PaidVia(last.paid_via) if last.paid_via else None
                else:
                    paid_at = paid_by = paid_via = None
                character_id = next(
                    (row.inviter_character_id for row in group if row.inviter_character_id is not None), None
                )
                member_name = None
                if character_id is not None:
                    char = await self._session.get(WowCharacter, character_id)
                    if char is not None and char.member_id is not None:
                        member = await self._session.get(Member, char.member_id)
                        if member is not None:
                            member_name = member.display_name
                payouts.append(
                    RecruitPayout(
                        event_id=drive.id,
                        title=drive.title,
                        settles_at=settles_at,
                        inviter=inviter,
                        member_name=member_name,
                        recruits=[row.recruit_name for row in group],
                        copper=DRIVE_PRIZE_COPPER,
                        paid_at=paid_at,
                        paid_by=paid_by,
                        paid_via=paid_via,
                    )
                )
        payouts.sort(key=lambda payout: payout.paid_at is not None)
        return payouts

    async def mark_paid(self, event_id: UUID, inviter: str, officer_name: str, *, now: datetime | None = None) -> None:
        """Mark this inviter's qualified unpaid recruits in this drive paid (their drive-winner prize). Idempotent."""
        now = now or datetime.now(UTC)
        rows = (
            (
                await self._session.execute(
                    select(RecruitmentRecruit).where(
                        RecruitmentRecruit.event_id == event_id,
                        RecruitmentRecruit.inviter_name == inviter,
                        RecruitmentRecruit.status == "qualified",
                        RecruitmentRecruit.paid_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.paid_at = now
            row.paid_by = officer_name
            row.paid_via = "site"
        await self._session.commit()
