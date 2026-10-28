"""DI providers for the member-links domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.member_links.services import MemberLinksService

provide_member_links_service = create_service_provider(MemberLinksService)
