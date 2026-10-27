"""DI providers for the addons domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.addons.services import AddonsService

provide_addons_service = create_service_provider(AddonsService)
