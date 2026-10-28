"""DI providers for the event_series domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.event_series.services import EventSeriesService

provide_event_series_service = create_service_provider(EventSeriesService)
