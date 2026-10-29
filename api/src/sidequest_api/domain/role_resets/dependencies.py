"""DI providers for the role_resets domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.role_resets.services import MemberRoleResetsService

provide_role_resets_service = create_service_provider(MemberRoleResetsService)
