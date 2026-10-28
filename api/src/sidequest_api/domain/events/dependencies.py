"""DI providers for the events domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.events.services import EventSignupsService, EventsService

provide_events_service = create_service_provider(EventsService)
provide_event_signups_service = create_service_provider(EventSignupsService)
