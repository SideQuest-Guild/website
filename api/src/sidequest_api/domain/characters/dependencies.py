"""DI providers for the characters domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.characters.services import CharactersService

provide_characters_service = create_service_provider(CharactersService)
