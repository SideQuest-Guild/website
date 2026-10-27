"""DI providers for the raids domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.raids.services import RaidSignupsService, RaidsService

provide_raids_service = create_service_provider(RaidsService)
provide_raid_signups_service = create_service_provider(RaidSignupsService)
