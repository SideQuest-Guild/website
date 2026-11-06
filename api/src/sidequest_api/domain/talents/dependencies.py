"""DI providers for the talents domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.talents.services import TalentBuildsService

provide_talent_builds_service = create_service_provider(TalentBuildsService)
