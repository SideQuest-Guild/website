"""Guild configuration endpoints."""

from litestar import Controller, get, patch
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, JSONBody

from sidequest_api.domain.guilds.dependencies import provide_guild_config_service
from sidequest_api.domain.guilds.services import GuildConfigService
from sidequest_common.schemas import GuildConfigSchema, GuildConfigUpdate


class GuildConfigController(Controller):
    """``/api/guilds/{guild_id}/config``."""

    path = "/config"
    tags = ["Guild Config"]
    dependencies = {"guild_config_service": Provide(provide_guild_config_service)}

    @get("/", operation_id="GetGuildConfig")
    async def get_config(
        self, guild_id: FromPath[int], guild_config_service: NamedDependency[GuildConfigService]
    ) -> GuildConfigSchema:
        """The guild's config (created with defaults on first access)."""
        config = await guild_config_service.get_or_create_config(guild_id)
        return GuildConfigSchema.model_validate(config)

    @patch("/", operation_id="UpdateGuildConfig")
    async def update_config(
        self,
        guild_id: FromPath[int],
        data: JSONBody[GuildConfigUpdate],
        guild_config_service: NamedDependency[GuildConfigService],
    ) -> GuildConfigSchema:
        """Change only the fields present in the body."""
        config = await guild_config_service.update_config(guild_id, data)
        return GuildConfigSchema.model_validate(config)
