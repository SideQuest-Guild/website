"""DI providers for the role menus domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.role_menus.services import RoleMenuService

provide_role_menu_service = create_service_provider(RoleMenuService)
