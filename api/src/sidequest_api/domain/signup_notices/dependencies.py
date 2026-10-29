"""DI providers for the signup_notices domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.members.services import MembersService

provide_members_service = create_service_provider(MembersService)
