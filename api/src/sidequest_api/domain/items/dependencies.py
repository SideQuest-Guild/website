"""DI providers for the items domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.items.services import ItemsService

provide_items_service = create_service_provider(ItemsService)
