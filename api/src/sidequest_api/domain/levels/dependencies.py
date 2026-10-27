"""DI providers for the leveling domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.levels.services import LevelRoleService, MemberLevelService

provide_member_level_service = create_service_provider(MemberLevelService)
provide_level_role_service = create_service_provider(LevelRoleService)
