"""Leveling domain services: XP from chat, voice, events and #lfg groups; ranks, leaderboard, level-role rewards."""

import random
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import HTTPException, NotFoundException
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects import postgresql, sqlite

from sidequest_common.leveling import level_for_xp, level_progress
from sidequest_common.models import (
    EventSignup,
    GroupSession,
    GroupSessionMember,
    GuildEvent,
    LevelRole,
    Member,
    MemberActivityHour,
    MemberLevel,
    XPGrant,
)
from sidequest_common.schemas import (
    COUNTED_GROUP_MINUTES,
    EVENT_XP,
    EVENT_XP_GRACE_HOURS,
    GROUP_XP,
    VOICE_XP_PER_MINUTE,
    XP_LOOKBACK_DAYS,
    LeaderboardEntry,
    LeaderboardPage,
    MessageBackfillBucket,
    MessageBackfillResult,
    RankSchema,
    XPAwardResult,
    XPGrantResult,
    XPSource,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from sidequest_common.models.guild import GuildConfig

MIN_COUNTED_PEAK_SIZE = 2
"""A group pays XP only if two or more members were ever in it, matching the Party Animal badge."""


def _hour_start(moment: datetime) -> datetime:
    """``moment`` truncated to its UTC hour, for ``MemberActivityHour.hour_start``."""
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _activity_insert(session: AsyncSession) -> Callable[..., postgresql.Insert | sqlite.Insert]:
    """The ``INSERT ... ON CONFLICT`` builder for ``session``'s dialect: Postgres in prod, SQLite in tests."""
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
    return postgresql.insert if dialect == "postgresql" else sqlite.insert


async def _bump_activity_hour(
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    hour_start: datetime,
    *,
    messages: int = 0,
    voice_minutes: int = 0,
    chat_xp: int = 0,
    voice_xp: int = 0,
) -> None:
    """Add to one member's hourly activity row, creating it at zero if it doesn't exist. Doesn't commit."""
    if not (messages or voice_minutes or chat_xp or voice_xp):
        return
    stmt = _activity_insert(session)(MemberActivityHour).values(
        guild_id=guild_id,
        user_id=user_id,
        hour_start=hour_start,
        messages=messages,
        voice_minutes=voice_minutes,
        chat_xp=chat_xp,
        voice_xp=voice_xp,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["guild_id", "user_id", "hour_start"],
        set_={
            "messages": MemberActivityHour.messages + messages,
            "voice_minutes": MemberActivityHour.voice_minutes + voice_minutes,
            "chat_xp": MemberActivityHour.chat_xp + chat_xp,
            "voice_xp": MemberActivityHour.voice_xp + voice_xp,
        },
    )
    await session.execute(stmt)


def _add_xp(member: MemberLevel, amount: int, config: GuildConfig, level_roles: list[LevelRole]) -> XPAwardResult:
    """Add ``amount`` to ``member`` and work out the level and level-role changes it causes."""
    previous_level = member.level
    member.xp += amount
    member.level = level_for_xp(member.xp)
    earned_role_ids = [role.role_id for role in level_roles if previous_level < role.level <= member.level]
    remove_role_ids: list[int] = []
    if earned_role_ids and not config.level_roles_stack:
        highest_level = max(role.level for role in level_roles if role.level <= member.level)
        remove_role_ids = [role.role_id for role in level_roles if role.level < highest_level]
    return XPAwardResult(
        awarded=True,
        amount=amount,
        xp=member.xp,
        level=member.level,
        previous_level=previous_level,
        leveled_up=member.level > previous_level,
        earned_role_ids=earned_role_ids,
        remove_role_ids=remove_role_ids,
    )


class MemberLevelRepository(SQLAlchemyAsyncRepository[MemberLevel]):
    """MemberLevel persistence."""

    model_type = MemberLevel


class MemberLevelService(SQLAlchemyAsyncRepositoryService[MemberLevel]):
    """XP totals: awarding, overrides, rank, and leaderboard reads."""

    repository_type = MemberLevelRepository
    match_fields = ["guild_id", "user_id"]

    async def get_or_create(self, guild_id: int, user_id: int) -> MemberLevel:
        """The member's row, created at zero XP if it doesn't exist yet."""
        existing = await self.get_one_or_none(guild_id=guild_id, user_id=user_id)
        if existing is not None:
            return existing
        try:
            return await self.create(MemberLevel(guild_id=guild_id, user_id=user_id), auto_commit=True)
        except IntegrityError:
            # Another request created it between our read and insert. The failed flush poisons the session's
            # transaction, so roll back before reading the winner's row.
            await self.repository.session.rollback()
            return await self.get_one(guild_id=guild_id, user_id=user_id)

    async def _locked(self, guild_id: int, user_id: int) -> MemberLevel:
        """The member's row, locked for update (no-op on dialects without row locking, e.g. SQLite)."""
        stmt = (
            select(MemberLevel)
            .where(MemberLevel.guild_id == guild_id, MemberLevel.user_id == user_id)
            .with_for_update()
        )
        row = (await self.repository.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            # Raced with another insert between get_or_create and this lock attempt.
            row = (await self.repository.session.execute(stmt)).scalar_one()
        return row

    async def _locked_or_new(self, guild_id: int, user_id: int) -> MemberLevel:
        """The member's row, locked, or a new zero-XP row; nothing is committed, so one batch is one transaction."""
        stmt = (
            select(MemberLevel)
            .where(MemberLevel.guild_id == guild_id, MemberLevel.user_id == user_id)
            .with_for_update()
        )
        row = (await self.repository.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = MemberLevel(guild_id=guild_id, user_id=user_id, xp=0, level=0, message_count=0)
            self.repository.session.add(row)
            await self.repository.session.flush()
        return row

    async def award_xp(
        self, guild_id: int, user_id: int, config: GuildConfig, level_roles: list[LevelRole]
    ) -> XPAwardResult:
        """One message's worth of XP, honoring cooldown/enabled state and reporting level-role deltas.

        Every call adds one message to the current UTC hour's ``MemberActivityHour`` row, and the XP actually
        awarded (zero while on cooldown or leveling is off), in the same transaction.
        """
        await self.get_or_create(guild_id, user_id)
        member = await self._locked(guild_id, user_id)
        member.message_count += 1
        now = datetime.now(UTC)
        hour = _hour_start(now)
        on_cooldown = (
            member.last_xp_at is not None and (now - member.last_xp_at).total_seconds() < config.xp_cooldown_seconds
        )
        if not config.leveling_enabled or on_cooldown:
            await _bump_activity_hour(self.repository.session, guild_id, user_id, hour, messages=1)
            await self.repository.session.commit()
            return XPAwardResult(
                awarded=False,
                amount=0,
                xp=member.xp,
                level=member.level,
                previous_level=member.level,
                leveled_up=False,
            )

        member.last_xp_at = now
        result = _add_xp(member, random.randint(config.xp_min, config.xp_max), config, level_roles)  # noqa: S311
        await _bump_activity_hour(self.repository.session, guild_id, user_id, hour, messages=1, chat_xp=result.amount)
        await self.repository.session.commit()
        return result

    async def _grant(
        self,
        guild_id: int,
        user_id: int,
        *,
        amount: int,
        source: XPSource,
        config: GuildConfig,
        level_roles: list[LevelRole],
    ) -> XPGrantResult:
        """Add non-chat XP. Doesn't touch the chat cooldown or message count, and doesn't commit."""
        member = await self._locked_or_new(guild_id, user_id)
        result = _add_xp(member, amount, config, level_roles)
        return XPGrantResult(**result.model_dump(), user_id=user_id, source=source)

    async def grant_voice(
        self,
        guild_id: int,
        user_ids: Iterable[int],
        present_user_ids: Iterable[int],
        *,
        minutes: int,
        config: GuildConfig,
        level_roles: list[LevelRole],
    ) -> list[XPGrantResult]:
        """``VOICE_XP_PER_MINUTE`` per minute to each XP-eligible member.

        Records ``minutes`` of voice presence for every id in ``present_user_ids`` or ``user_ids`` (an old bot
        sends only ``user_ids``), even when leveling is disabled; only XP-eligible members (``user_ids``) get
        XP, and only while leveling is enabled.
        """
        session = self.repository.session
        now = datetime.now(UTC)
        hour = _hour_start(now)
        present = sorted(set(user_ids) | set(present_user_ids))  # a fixed lock order, so two batches can't deadlock
        for user_id in present:
            await _bump_activity_hour(session, guild_id, user_id, hour, voice_minutes=minutes)
        if not config.leveling_enabled:
            await session.commit()
            return []
        amount = VOICE_XP_PER_MINUTE * minutes
        results: list[XPGrantResult] = []
        for user_id in sorted(set(user_ids)):
            results.append(
                await self._grant(
                    guild_id, user_id, amount=amount, source=XPSource.VOICE, config=config, level_roles=level_roles
                )
            )
            await _bump_activity_hour(session, guild_id, user_id, hour, voice_xp=amount)
        await session.commit()
        return results

    async def sync_activity(
        self, guild_id: int, config: GuildConfig, level_roles: list[LevelRole], *, now: datetime | None = None
    ) -> list[XPGrantResult]:
        """Pay ``EVENT_XP`` per attended event and ``GROUP_XP`` per counted #lfg group, once each, in one transaction.

        Only events and groups from the last ``XP_LOOKBACK_DAYS`` count. Members holding a no-XP role (from their
        stored Discord roles) are skipped; the ``xp_grant`` ledger's unique key makes a concurrent call fail instead
        of paying twice.
        """
        if not config.leveling_enabled:
            return []
        reference = now or datetime.now(UTC)
        since = reference - timedelta(days=XP_LOOKBACK_DAYS)
        candidates = [
            *[
                (user_id, XPSource.EVENT, source_id)
                for user_id, source_id in await self._attended_events(since, reference)
            ],
            *[(user_id, XPSource.GROUP, source_id) for user_id, source_id in await self._counted_groups(since)],
        ]
        if not candidates:
            return []
        paid = await self._already_paid(guild_id, {source_id for _, _, source_id in candidates})
        blocked = await self._no_xp_members({user_id for user_id, _, _ in candidates}, config.no_xp_role_ids)
        amounts = {XPSource.EVENT: EVENT_XP, XPSource.GROUP: GROUP_XP}
        results: list[XPGrantResult] = []
        session = self.repository.session
        for user_id, source, source_id in sorted(set(candidates)):
            if (user_id, source, source_id) in paid or user_id in blocked:
                continue
            amount = amounts[source]
            session.add(XPGrant(guild_id=guild_id, user_id=user_id, source=source, source_id=source_id, amount=amount))
            results.append(
                await self._grant(
                    guild_id, user_id, amount=amount, source=source, config=config, level_roles=level_roles
                )
            )
        await session.commit()
        return results

    async def _attended_events(self, since: datetime, now: datetime) -> list[tuple[int, UUID]]:
        """(Discord id, event id) for sign-ups that count as attended: marked "came", or a day passed untaken."""
        grace_cutoff = now - timedelta(hours=EVENT_XP_GRACE_HOURS)
        stmt = (
            select(Member.discord_id, GuildEvent.id)
            .select_from(EventSignup)
            .join(GuildEvent, GuildEvent.id == EventSignup.event_id)
            .join(Member, Member.id == EventSignup.member_id)
            .where(
                GuildEvent.status != "cancelled",
                GuildEvent.starts_at >= since,
                GuildEvent.starts_at < now,
                or_(
                    and_(GuildEvent.attendance_taken_at.is_not(None), EventSignup.attended.is_(True)),
                    and_(
                        GuildEvent.attendance_taken_at.is_(None),
                        EventSignup.status == "signed",
                        GuildEvent.starts_at < grace_cutoff,
                    ),
                ),
            )
        )
        return [(int(user_id), event_id) for user_id, event_id in (await self.repository.session.execute(stmt)).all()]

    async def _counted_groups(self, since: datetime) -> list[tuple[int, UUID]]:
        """(Discord id, session id) for ended #lfg groups where the member spent ``COUNTED_GROUP_MINUTES`` or more."""
        stmt = (
            select(GroupSessionMember.discord_id, GroupSession.id)
            .join(GroupSession, GroupSession.id == GroupSessionMember.session_id)
            .where(
                GroupSession.ended_at.is_not(None),
                GroupSession.ended_at >= since,
                GroupSession.peak_size >= MIN_COUNTED_PEAK_SIZE,
                GroupSession.grouped_minutes >= COUNTED_GROUP_MINUTES,
                GroupSessionMember.minutes >= COUNTED_GROUP_MINUTES,
            )
        )
        return [
            (int(user_id), session_id) for user_id, session_id in (await self.repository.session.execute(stmt)).all()
        ]

    async def _already_paid(self, guild_id: int, source_ids: set[UUID]) -> set[tuple[int, str, UUID]]:
        stmt = select(XPGrant.user_id, XPGrant.source, XPGrant.source_id).where(
            XPGrant.guild_id == guild_id, XPGrant.source_id.in_(source_ids)
        )
        return {
            (int(user_id), source, source_id)
            for user_id, source, source_id in await self.repository.session.execute(stmt)
        }

    async def _no_xp_members(self, user_ids: set[int], no_xp_role_ids: list[int]) -> set[int]:
        """Discord ids among ``user_ids`` whose stored roles include a no-XP role."""
        if not no_xp_role_ids:
            return set()
        blocked_roles = set(no_xp_role_ids)
        stmt = select(Member.discord_id, Member.roles).where(Member.discord_id.in_(user_ids))
        return {
            int(discord_id)
            for discord_id, roles in await self.repository.session.execute(stmt)
            if blocked_roles & {int(role) for role in roles or []}
        }

    async def set_xp(self, guild_id: int, user_id: int, xp: int) -> MemberLevel:
        """Overwrite a member's XP total; level is recomputed."""
        member = await self.get_or_create(guild_id, user_id)
        member.xp = xp
        member.level = level_for_xp(xp)
        return await self.update(member, auto_commit=True)

    async def get_rank(self, guild_id: int, user_id: int) -> RankSchema:
        """A member's standing; unknown members get zeros instead of a 404."""
        member = await self.get_one_or_none(guild_id=guild_id, user_id=user_id)
        if member is None:
            progress = level_progress(0)
            return RankSchema(
                user_id=user_id,
                rank=None,
                xp=0,
                level=0,
                message_count=0,
                xp_into_level=progress.xp_into_level,
                xp_for_next_level=progress.xp_for_next_level,
            )
        rank = None
        if member.xp > 0:
            stmt = (
                select(func.count())
                .select_from(MemberLevel)
                .where(MemberLevel.guild_id == guild_id, MemberLevel.xp > member.xp)
            )
            higher = (await self.repository.session.execute(stmt)).scalar_one()
            rank = higher + 1
        progress = level_progress(member.xp)
        return RankSchema(
            user_id=user_id,
            rank=rank,
            xp=member.xp,
            level=member.level,
            message_count=member.message_count,
            xp_into_level=progress.xp_into_level,
            xp_for_next_level=progress.xp_for_next_level,
        )

    async def get_leaderboard(self, guild_id: int, *, limit: int, offset: int) -> LeaderboardPage:
        """Highest XP first, ties broken by ascending user ID."""
        total_stmt = (
            select(func.count()).select_from(MemberLevel).where(MemberLevel.guild_id == guild_id, MemberLevel.xp > 0)
        )
        total = (await self.repository.session.execute(total_stmt)).scalar_one()
        rows_stmt = (
            select(MemberLevel)
            .where(MemberLevel.guild_id == guild_id, MemberLevel.xp > 0)
            .order_by(MemberLevel.xp.desc(), MemberLevel.user_id.asc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.repository.session.execute(rows_stmt)).scalars().all()
        entries = [
            LeaderboardEntry(
                rank=offset + i + 1,
                user_id=row.user_id,
                xp=row.xp,
                level=row.level,
                message_count=row.message_count,
            )
            for i, row in enumerate(rows)
        ]
        return LeaderboardPage(entries=entries, total=total, limit=limit, offset=offset)

    async def backfill_messages(self, guild_id: int, buckets: list[MessageBackfillBucket]) -> MessageBackfillResult:
        """Message counts read once from Discord channel history.

        Sets each bucket's ``messages`` to the higher of the existing and reported value (idempotent and safe to
        replay), never lowers a live count, and never touches ``MemberLevel.message_count`` or XP.
        """
        if not buckets:
            return MessageBackfillResult(buckets=0)
        merged: dict[tuple[int, datetime], int] = {}
        for bucket in buckets:
            key = (bucket.user_id, _hour_start(bucket.hour_start))
            merged[key] = max(merged.get(key, 0), bucket.messages)
        session = self.repository.session
        insert_fn = _activity_insert(session)
        values = [
            {"guild_id": guild_id, "user_id": user_id, "hour_start": hour, "messages": messages}
            for (user_id, hour), messages in merged.items()
        ]
        stmt = insert_fn(MemberActivityHour).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id", "user_id", "hour_start"],
            set_={
                "messages": case(
                    (stmt.excluded.messages > MemberActivityHour.messages, stmt.excluded.messages),
                    else_=MemberActivityHour.messages,
                )
            },
        )
        await session.execute(stmt)
        await session.commit()
        return MessageBackfillResult(buckets=len(values))


class LevelRoleRepository(SQLAlchemyAsyncRepository[LevelRole]):
    """LevelRole persistence."""

    model_type = LevelRole


class LevelRoleService(SQLAlchemyAsyncRepositoryService[LevelRole]):
    """Level-role reward CRUD."""

    repository_type = LevelRoleRepository
    match_fields = ["guild_id", "level"]

    async def list_for_guild(self, guild_id: int) -> list[LevelRole]:
        """Rewards sorted by level, lowest first."""
        stmt = select(LevelRole).where(LevelRole.guild_id == guild_id).order_by(LevelRole.level.asc())
        return list((await self.repository.session.execute(stmt)).scalars().all())

    async def set_role(self, guild_id: int, level: int, role_id: int) -> LevelRole:
        """Grant ``role_id`` at ``level``, replacing any existing reward for that level."""
        conflict_stmt = select(LevelRole).where(
            LevelRole.guild_id == guild_id, LevelRole.role_id == role_id, LevelRole.level != level
        )
        conflict = (await self.repository.session.execute(conflict_stmt)).scalar_one_or_none()
        if conflict is not None:
            msg = f"Role {role_id} is already rewarded at level {conflict.level}"
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=msg)
        existing = await self.get_one_or_none(guild_id=guild_id, level=level)
        if existing is not None:
            existing.role_id = role_id
            return await self.update(existing, auto_commit=True)
        return await self.create(LevelRole(guild_id=guild_id, level=level, role_id=role_id), auto_commit=True)

    async def delete_role(self, guild_id: int, level: int) -> None:
        """Remove the reward at ``level``. Raises NotFoundException if none."""
        existing = await self.get_one_or_none(guild_id=guild_id, level=level)
        if existing is None:
            msg = f"No level-role reward at level {level}"
            raise NotFoundException(msg)
        await self.delete(existing.id, auto_commit=True)
