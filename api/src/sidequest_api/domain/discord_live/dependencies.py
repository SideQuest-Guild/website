"""DI providers for the discord_live domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.discord_live.services import DiscordLiveService

provide_discord_live_service = create_service_provider(DiscordLiveService)
