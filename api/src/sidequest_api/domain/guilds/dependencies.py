"""DI providers for the guilds domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.guilds.services import GuildConfigService

provide_guild_config_service = create_service_provider(GuildConfigService)
