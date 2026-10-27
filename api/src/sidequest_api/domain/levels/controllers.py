"""Leveling endpoints."""

from http import HTTPStatus
from typing import Annotated

from litestar import Controller, delete, get, post, put
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, JSONBody, PathParameter, QueryParameter

from sidequest_api.domain.guilds.dependencies import provide_guild_config_service
from sidequest_api.domain.guilds.services import GuildConfigService
from sidequest_api.domain.levels.dependencies import provide_level_role_service, provide_member_level_service
from sidequest_api.domain.levels.services import LevelRoleService, MemberLevelService
from sidequest_common.schemas import (
    LeaderboardPage,
    LevelRoleSchema,
    LevelRoleUpsert,
    MemberLevelSchema,
    RankSchema,
    SetXPRequest,
    XPAwardResult,
)


class LevelsController(Controller):
    """``/api/guilds/{guild_id:int}``."""

    path = "/"
    tags = ["Leveling"]
    dependencies = {
        "guild_config_service": Provide(provide_guild_config_service),
        "member_level_service": Provide(provide_member_level_service),
        "level_role_service": Provide(provide_level_role_service),
    }

    @post("/members/{user_id:int}/xp", operation_id="AwardXP", status_code=HTTPStatus.OK)
    async def award_xp(
        self,
        guild_id: FromPath[int],
        user_id: FromPath[int],
        guild_config_service: NamedDependency[GuildConfigService],
        member_level_service: NamedDependency[MemberLevelService],
        level_role_service: NamedDependency[LevelRoleService],
    ) -> XPAwardResult:
        """One message's worth of XP, honoring cooldown and the leveling-enabled flag."""
        config = await guild_config_service.get_or_create_config(guild_id)
        level_roles = await level_role_service.list_for_guild(guild_id)
        return await member_level_service.award_xp(guild_id, user_id, config, level_roles)

    @put("/members/{user_id:int}/xp", operation_id="SetXP")
    async def set_xp(
        self,
        guild_id: FromPath[int],
        user_id: FromPath[int],
        data: JSONBody[SetXPRequest],
        member_level_service: NamedDependency[MemberLevelService],
    ) -> MemberLevelSchema:
        """Overwrite a member's XP total; level is recomputed."""
        member = await member_level_service.set_xp(guild_id, user_id, data.xp)
        return MemberLevelSchema.model_validate(member)

    @get("/members/{user_id:int}/rank", operation_id="GetRank")
    async def get_rank(
        self,
        guild_id: FromPath[int],
        user_id: FromPath[int],
        member_level_service: NamedDependency[MemberLevelService],
    ) -> RankSchema:
        """A member's standing; members with no XP yet get zeros instead of a 404."""
        return await member_level_service.get_rank(guild_id, user_id)

    @get("/leaderboard", operation_id="GetLeaderboard")
    async def get_leaderboard(
        self,
        guild_id: FromPath[int],
        member_level_service: NamedDependency[MemberLevelService],
        limit: Annotated[int, QueryParameter(ge=1, le=100)] = 10,
        offset: Annotated[int, QueryParameter(ge=0)] = 0,
    ) -> LeaderboardPage:
        """Highest XP first."""
        return await member_level_service.get_leaderboard(guild_id, limit=limit, offset=offset)

    @get("/level-roles", operation_id="ListLevelRoles")
    async def list_level_roles(
        self, guild_id: FromPath[int], level_role_service: NamedDependency[LevelRoleService]
    ) -> list[LevelRoleSchema]:
        """Level rewards, lowest level first."""
        roles = await level_role_service.list_for_guild(guild_id)
        return [LevelRoleSchema.model_validate(role) for role in roles]

    @put("/level-roles/{level:int}", operation_id="SetLevelRole")
    async def set_level_role(
        self,
        guild_id: FromPath[int],
        level: Annotated[int, PathParameter(ge=1, le=1000)],
        data: JSONBody[LevelRoleUpsert],
        level_role_service: NamedDependency[LevelRoleService],
    ) -> LevelRoleSchema:
        """Grant ``role_id`` at ``level`` (replaces any existing reward for that level)."""
        role = await level_role_service.set_role(guild_id, level, data.role_id)
        return LevelRoleSchema.model_validate(role)

    @delete("/level-roles/{level:int}", operation_id="DeleteLevelRole")
    async def delete_level_role(
        self,
        guild_id: FromPath[int],
        level: Annotated[int, PathParameter(ge=1, le=1000)],
        level_role_service: NamedDependency[LevelRoleService],
    ) -> None:
        """Remove the reward at ``level``."""
        await level_role_service.delete_role(guild_id, level)
