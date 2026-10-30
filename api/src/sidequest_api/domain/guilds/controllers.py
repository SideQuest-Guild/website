"""Guild configuration endpoints."""

from litestar import Controller, get, patch
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody

from sidequest_api.domain.guilds.dependencies import provide_guild_config_service
from sidequest_api.domain.guilds.services import GuildConfigService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import GuildConfigSchema, GuildConfigUpdate


class GuildConfigController(Controller):
    """``/api/guilds/{guild_id}/config``."""

    path = "/config"
    tags = ["Guild settings"]
    dependencies = {"guild_config_service": Provide(provide_guild_config_service)}

    @get(
        "/",
        operation_id="GetGuildConfig",
        summary="Get guild settings",
        description="Returns the guild's settings, created with their defaults on first access.",
        response_description="The guild's settings.",
    )
    async def get_config(
        self, guild_id: GuildIdPath, guild_config_service: NamedDependency[GuildConfigService]
    ) -> GuildConfigSchema:
        config = await guild_config_service.get_or_create_config(guild_id)
        return GuildConfigSchema.model_validate(config)

    @patch(
        "/",
        operation_id="UpdateGuildConfig",
        summary="Update guild settings",
        description="Changes only the fields present in the request body.",
        response_description="The guild's updated settings.",
        responses={400: ResponseSpec(None, description="xp_min is greater than xp_max.")},
    )
    async def update_config(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[GuildConfigUpdate],
        guild_config_service: NamedDependency[GuildConfigService],
    ) -> GuildConfigSchema:
        config = await guild_config_service.update_config(guild_id, data)
        return GuildConfigSchema.model_validate(config)
