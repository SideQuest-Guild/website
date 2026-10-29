"""DI providers for the guild_roles domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.guild_roles.services import GuildRolesService

provide_guild_roles_service = create_service_provider(GuildRolesService)
