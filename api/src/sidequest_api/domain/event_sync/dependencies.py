"""DI providers for the event-sync domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.event_sync.services import EventSyncService

provide_event_sync_service = create_service_provider(EventSyncService)
