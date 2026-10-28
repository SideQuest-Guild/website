"""DI providers for the raid-sync domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.raid_sync.services import RaidSyncService

provide_raid_sync_service = create_service_provider(RaidSyncService)
