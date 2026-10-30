"""DI providers for the calendar domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.calendar.services import CalendarService

provide_calendar_service = create_service_provider(CalendarService)
