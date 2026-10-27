"""Role Menus endpoints: menus and their button options."""

from uuid import UUID  # litestar resolves Mapped[]/path param annotations at runtime

from litestar import Controller, delete, get, patch, post, put
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, JSONBody

from sidequest_api.domain.role_menus.dependencies import provide_role_menu_service
from sidequest_api.domain.role_menus.services import RoleMenuService
from sidequest_common.schemas import RoleMenuCreate, RoleMenuOptionUpsert, RoleMenuSchema, RoleMenuUpdate


class RoleMenusController(Controller):
    """``/api/guilds/{guild_id:int}/role-menus``."""

    path = "/role-menus"
    tags = ["Role Menus"]
    dependencies = {"role_menu_service": Provide(provide_role_menu_service)}

    @post("/", operation_id="CreateRoleMenu", status_code=201)
    async def create_role_menu(
        self,
        guild_id: FromPath[int],
        data: JSONBody[RoleMenuCreate],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> RoleMenuSchema:
        """Create a menu (no message yet; the bot posts it and PATCHes ``message_id``)."""
        menu = await role_menu_service.create_menu(guild_id, data)
        return RoleMenuSchema.model_validate(menu)

    @get("/", operation_id="ListRoleMenus")
    async def list_role_menus(
        self, guild_id: FromPath[int], role_menu_service: NamedDependency[RoleMenuService]
    ) -> list[RoleMenuSchema]:
        """All menus in the guild."""
        menus = await role_menu_service.list_menus(guild_id)
        return [RoleMenuSchema.model_validate(menu) for menu in menus]

    @get("/{menu_id:uuid}", operation_id="GetRoleMenu")
    async def get_role_menu(
        self,
        guild_id: FromPath[int],
        menu_id: FromPath[UUID],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> RoleMenuSchema:
        """One menu with its options."""
        menu = await role_menu_service.get_menu(guild_id, menu_id)
        return RoleMenuSchema.model_validate(menu)

    @patch("/{menu_id:uuid}", operation_id="UpdateRoleMenu")
    async def update_role_menu(
        self,
        guild_id: FromPath[int],
        menu_id: FromPath[UUID],
        data: JSONBody[RoleMenuUpdate],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> RoleMenuSchema:
        """Change only the fields present in the body."""
        menu = await role_menu_service.update_menu(guild_id, menu_id, data)
        return RoleMenuSchema.model_validate(menu)

    @delete("/{menu_id:uuid}", operation_id="DeleteRoleMenu")
    async def delete_role_menu(
        self,
        guild_id: FromPath[int],
        menu_id: FromPath[UUID],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> None:
        """Delete a menu and its options."""
        await role_menu_service.delete_menu(guild_id, menu_id)

    @put("/{menu_id:uuid}/options/{role_id:int}", operation_id="UpsertRoleMenuOption")
    async def upsert_role_menu_option(
        self,
        guild_id: FromPath[int],
        menu_id: FromPath[UUID],
        role_id: FromPath[int],
        data: JSONBody[RoleMenuOptionUpsert],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> RoleMenuSchema:
        """Add or edit the button for ``role_id``; returns the updated menu."""
        menu = await role_menu_service.upsert_option(guild_id, menu_id, role_id, data)
        return RoleMenuSchema.model_validate(menu)

    @delete("/{menu_id:uuid}/options/{role_id:int}", operation_id="DeleteRoleMenuOption", status_code=200)
    async def delete_role_menu_option(
        self,
        guild_id: FromPath[int],
        menu_id: FromPath[UUID],
        role_id: FromPath[int],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> RoleMenuSchema:
        """Remove the button for ``role_id``; returns the updated menu."""
        menu = await role_menu_service.delete_option(guild_id, menu_id, role_id)
        return RoleMenuSchema.model_validate(menu)
