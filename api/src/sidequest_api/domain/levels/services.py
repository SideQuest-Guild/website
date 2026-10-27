"""Leveling domain services: XP awards, ranks, leaderboard, and level-role rewards."""

import random
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import HTTPException, NotFoundException
from sqlalchemy import func, select

from sidequest_common.leveling import level_for_xp, level_progress
from sidequest_common.models import LevelRole, MemberLevel
from sidequest_common.schemas import LeaderboardEntry, LeaderboardPage, RankSchema, XPAwardResult

if TYPE_CHECKING:
    from sidequest_common.models.guild import GuildConfig


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

    async def award_xp(
        self, guild_id: int, user_id: int, config: GuildConfig, level_roles: list[LevelRole]
    ) -> XPAwardResult:
        """One message's worth of XP, honoring cooldown/enabled state and reporting level-role deltas."""
        await self.get_or_create(guild_id, user_id)
        member = await self._locked(guild_id, user_id)
        member.message_count += 1
        now = datetime.now(UTC)
        previous_level = member.level
        on_cooldown = (
            member.last_xp_at is not None and (now - member.last_xp_at).total_seconds() < config.xp_cooldown_seconds
        )
        if not config.leveling_enabled or on_cooldown:
            await self.repository.session.commit()
            return XPAwardResult(
                awarded=False,
                amount=0,
                xp=member.xp,
                level=member.level,
                previous_level=previous_level,
                leveled_up=False,
            )

        amount = random.randint(config.xp_min, config.xp_max)  # noqa: S311
        member.xp += amount
        member.last_xp_at = now
        member.level = level_for_xp(member.xp)
        leveled_up = member.level > previous_level
        earned_role_ids = [role.role_id for role in level_roles if previous_level < role.level <= member.level]
        remove_role_ids: list[int] = []
        if earned_role_ids and not config.level_roles_stack:
            reachable_levels = [role.level for role in level_roles if role.level <= member.level]
            highest_level = max(reachable_levels)
            remove_role_ids = [role.role_id for role in level_roles if role.level < highest_level]
        await self.repository.session.commit()
        return XPAwardResult(
            awarded=True,
            amount=amount,
            xp=member.xp,
            level=member.level,
            previous_level=previous_level,
            leveled_up=leveled_up,
            earned_role_ids=earned_role_ids,
            remove_role_ids=remove_role_ids,
        )

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
