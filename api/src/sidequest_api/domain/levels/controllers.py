"""Leveling endpoints."""

from http import HTTPStatus
from typing import Annotated

from litestar import Controller, delete, get, post, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.guilds.dependencies import provide_guild_config_service
from sidequest_api.domain.guilds.services import GuildConfigService
from sidequest_api.domain.levels.dependencies import provide_level_role_service, provide_member_level_service
from sidequest_api.domain.levels.services import LevelRoleService, MemberLevelService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import (
    LeaderboardPage,
    LevelRoleSchema,
    LevelRoleUpsert,
    MemberLevelSchema,
    MessageBackfill,
    MessageBackfillResult,
    RankSchema,
    SetXPRequest,
    VoiceXPRequest,
    XPActivityReport,
    XPAwardResult,
    XPGrantResult,
)
from sidequest_common.settings import WebSettings


class LevelsController(Controller):
    """``/api/guilds/{guild_id:int}``."""

    path = "/"
    tags = ["Leveling"]
    dependencies = {
        "guild_config_service": Provide(provide_guild_config_service),
        "member_level_service": Provide(provide_member_level_service),
        "level_role_service": Provide(provide_level_role_service),
    }

    @post(
        "/members/{user_id:int}/xp",
        operation_id="AwardXP",
        status_code=HTTPStatus.OK,
        summary="Award XP",
        description=(
            "Awards one message's worth of XP to a member, honoring the per-member cooldown and the "
            "guild's leveling-enabled setting."
        ),
        response_description="The XP award result, with any level-role changes.",
    )
    async def award_xp(
        self,
        guild_id: GuildIdPath,
        user_id: Annotated[int, Parameter(description="The member's Discord user ID.")],
        guild_config_service: NamedDependency[GuildConfigService],
        member_level_service: NamedDependency[MemberLevelService],
        level_role_service: NamedDependency[LevelRoleService],
    ) -> XPAwardResult:
        config = await guild_config_service.get_or_create_config(guild_id)
        level_roles = await level_role_service.list_for_guild(guild_id)
        return await member_level_service.award_xp(guild_id, user_id, config, level_roles)

    @post(
        "/xp/voice",
        operation_id="GrantVoiceXP",
        status_code=HTTPStatus.OK,
        summary="Grant voice XP",
        description=(
            "Gives each XP-eligible listed member (user_ids) XP for the minutes they spent in voice, and records "
            "those minutes for every member present under the stats voice rule (present_user_ids), even while "
            "leveling is off. The bot decides who's XP-eligible: someone else in the channel, not deafened, "
            "outside the AFK channel and no-XP channels or roles."
        ),
        response_description="One result per XP-eligible member, with any level-up and level-role changes.",
    )
    async def grant_voice_xp(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[VoiceXPRequest],
        guild_config_service: NamedDependency[GuildConfigService],
        member_level_service: NamedDependency[MemberLevelService],
        level_role_service: NamedDependency[LevelRoleService],
    ) -> list[XPGrantResult]:
        config = await guild_config_service.get_or_create_config(guild_id)
        level_roles = await level_role_service.list_for_guild(guild_id)
        return await member_level_service.grant_voice(
            guild_id,
            data.user_ids,
            data.present_user_ids,
            minutes=data.minutes,
            config=config,
            level_roles=level_roles,
        )

    @put(
        "/activity/messages",
        operation_id="BackfillMessages",
        status_code=HTTPStatus.OK,
        summary="Backfill message counts",
        description=(
            "Stores message counts read once from Discord channel history, per member per UTC hour. Sets each "
            "bucket's count to the higher of the existing and reported value, so replaying history is always "
            "safe and never lowers a live count. Doesn't touch lifetime message counts or XP."
        ),
        response_description="How many buckets were touched.",
    )
    async def backfill_messages(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[MessageBackfill],
        member_level_service: NamedDependency[MemberLevelService],
    ) -> MessageBackfillResult:
        return await member_level_service.backfill_messages(guild_id, data.buckets)

    @post(
        "/xp/activity",
        operation_id="SyncActivityXP",
        status_code=HTTPStatus.OK,
        summary="Pay event and group XP",
        description=(
            "Pays XP once per member for each guild event they attended and each #lfg group they spent ten or "
            "more minutes in, from the last 30 days. Safe to poll: anything already paid is skipped. Returns 404 "
            "for any guild_id other than the SideQuest server, since events and groups belong to it."
        ),
        response_description="The XP paid by this call, with any level-up and level-role changes.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server.")},
    )
    async def sync_activity_xp(
        self,
        guild_id: GuildIdPath,
        guild_config_service: NamedDependency[GuildConfigService],
        member_level_service: NamedDependency[MemberLevelService],
        level_role_service: NamedDependency[LevelRoleService],
        web_settings: NamedDependency[WebSettings],
    ) -> XPActivityReport:
        if guild_id != web_settings.GUILD_ID:
            msg = f"No guild {guild_id}"
            raise NotFoundException(msg)
        config = await guild_config_service.get_or_create_config(guild_id)
        level_roles = await level_role_service.list_for_guild(guild_id)
        return XPActivityReport(grants=await member_level_service.sync_activity(guild_id, config, level_roles))

    @put(
        "/members/{user_id:int}/xp",
        operation_id="SetXP",
        summary="Set a member's XP",
        description="Overwrites a member's XP total. The level is recomputed from the new total.",
        response_description="The member's updated level and XP.",
    )
    async def set_xp(
        self,
        guild_id: GuildIdPath,
        user_id: Annotated[int, Parameter(description="The member's Discord user ID.")],
        data: JSONBody[SetXPRequest],
        member_level_service: NamedDependency[MemberLevelService],
    ) -> MemberLevelSchema:
        member = await member_level_service.set_xp(guild_id, user_id, data.xp)
        return MemberLevelSchema.model_validate(member)

    @get(
        "/members/{user_id:int}/rank",
        operation_id="GetRank",
        summary="Get a member's rank",
        description="Returns a member's leaderboard standing. A member with no XP yet gets zeros instead of a 404.",
        response_description="The member's rank, level, and XP.",
    )
    async def get_rank(
        self,
        guild_id: GuildIdPath,
        user_id: Annotated[int, Parameter(description="The member's Discord user ID.")],
        member_level_service: NamedDependency[MemberLevelService],
    ) -> RankSchema:
        return await member_level_service.get_rank(guild_id, user_id)

    @get(
        "/leaderboard",
        operation_id="GetLeaderboard",
        summary="Get the XP leaderboard",
        description="Returns a page of the guild's XP leaderboard, highest XP first.",
        response_description="A page of leaderboard entries.",
    )
    async def get_leaderboard(
        self,
        guild_id: GuildIdPath,
        member_level_service: NamedDependency[MemberLevelService],
        limit: Annotated[int, Parameter(description="The maximum number of entries to return.", ge=1, le=100)] = 10,
        offset: Annotated[int, Parameter(description="The number of leading entries to skip.", ge=0)] = 0,
    ) -> LeaderboardPage:
        return await member_level_service.get_leaderboard(guild_id, limit=limit, offset=offset)

    @get(
        "/level-roles",
        operation_id="ListLevelRoles",
        summary="List level-role rewards",
        description="Returns the guild's level-role rewards, lowest level first.",
        response_description="The guild's level-role rewards.",
    )
    async def list_level_roles(
        self, guild_id: GuildIdPath, level_role_service: NamedDependency[LevelRoleService]
    ) -> list[LevelRoleSchema]:
        roles = await level_role_service.list_for_guild(guild_id)
        return [LevelRoleSchema.model_validate(role) for role in roles]

    @put(
        "/level-roles/{level:int}",
        operation_id="SetLevelRole",
        summary="Set a level-role reward",
        description="Grants a Discord role at a level. This replaces any existing reward for that level.",
        response_description="The level-role reward.",
        responses={409: ResponseSpec(None, description="The role already rewards a different level.")},
    )
    async def set_level_role(
        self,
        guild_id: GuildIdPath,
        level: Annotated[int, Parameter(description="The level the reward is granted at.", ge=1, le=1000)],
        data: JSONBody[LevelRoleUpsert],
        level_role_service: NamedDependency[LevelRoleService],
    ) -> LevelRoleSchema:
        role = await level_role_service.set_role(guild_id, level, data.role_id)
        return LevelRoleSchema.model_validate(role)

    @delete(
        "/level-roles/{level:int}",
        operation_id="DeleteLevelRole",
        summary="Remove a level-role reward",
        description="Removes the level-role reward at a level.",
        response_description="The reward was removed.",
        responses={404: ResponseSpec(None, description="No level-role reward exists at that level.")},
    )
    async def delete_level_role(
        self,
        guild_id: GuildIdPath,
        level: Annotated[int, Parameter(description="The level the reward is granted at.", ge=1, le=1000)],
        level_role_service: NamedDependency[LevelRoleService],
    ) -> None:
        await level_role_service.delete_role(guild_id, level)
