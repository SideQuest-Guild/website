"""DI providers for the away domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.away.services import AwayService

provide_away_service = create_service_provider(AwayService)
