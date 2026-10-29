"""DI providers for the member_profiles domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.member_profiles.services import MemberProfilesService

provide_member_profiles_service = create_service_provider(MemberProfilesService)
