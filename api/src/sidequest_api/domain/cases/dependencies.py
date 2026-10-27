"""DI providers for the cases domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.cases.services import CasesService

provide_cases_service = create_service_provider(CasesService)
