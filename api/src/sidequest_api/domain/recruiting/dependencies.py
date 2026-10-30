"""DI providers for the recruiting domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.recruiting.services import RecruitingService

provide_recruiting_service = create_service_provider(RecruitingService)
