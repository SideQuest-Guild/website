"""Role Menus endpoints: menus and their button options."""

from typing import Annotated
from uuid import UUID  # litestar resolves Mapped[]/path param annotations at runtime

from litestar import Controller, delete, get, patch, post, put
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.role_menus.dependencies import provide_role_menu_service
from sidequest_api.domain.role_menus.services import RoleMenuService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import RoleMenuCreate, RoleMenuOptionUpsert, RoleMenuSchema, RoleMenuUpdate

_NOT_FOUND = ResponseSpec(None, description="No role menu with that ID exists in the guild.")


class RoleMenusController(Controller):
    """``/api/guilds/{guild_id:int}/role-menus``."""

    path = "/role-menus"
    tags = ["Role menus"]
    dependencies = {"role_menu_service": Provide(provide_role_menu_service)}

    @post(
        "/",
        operation_id="CreateRoleMenu",
        status_code=201,
        summary="Create a role menu",
        description="Creates a role menu with no message yet. The bot posts it, then PATCHes its message_id.",
        response_description="The created role menu.",
    )
    async def create_role_menu(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[RoleMenuCreate],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> RoleMenuSchema:
        menu = await role_menu_service.create_menu(guild_id, data)
        return RoleMenuSchema.model_validate(menu)

    @get(
        "/",
        operation_id="ListRoleMenus",
        summary="List role menus",
        description="Returns every role menu in the guild.",
        response_description="The guild's role menus.",
    )
    async def list_role_menus(
        self, guild_id: GuildIdPath, role_menu_service: NamedDependency[RoleMenuService]
    ) -> list[RoleMenuSchema]:
        menus = await role_menu_service.list_menus(guild_id)
        return [RoleMenuSchema.model_validate(menu) for menu in menus]

    @get(
        "/{menu_id:uuid}",
        operation_id="GetRoleMenu",
        summary="Get a role menu",
        description="Returns one role menu with its button options.",
        response_description="The role menu.",
        responses={404: _NOT_FOUND},
    )
    async def get_role_menu(
        self,
        guild_id: GuildIdPath,
        menu_id: Annotated[UUID, Parameter(description="The role menu's ID.")],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> RoleMenuSchema:
        menu = await role_menu_service.get_menu(guild_id, menu_id)
        return RoleMenuSchema.model_validate(menu)

    @patch(
        "/{menu_id:uuid}",
        operation_id="UpdateRoleMenu",
        summary="Update a role menu",
        description="Changes only the fields present in the request body.",
        response_description="The updated role menu.",
        responses={404: _NOT_FOUND},
    )
    async def update_role_menu(
        self,
        guild_id: GuildIdPath,
        menu_id: Annotated[UUID, Parameter(description="The role menu's ID.")],
        data: JSONBody[RoleMenuUpdate],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> RoleMenuSchema:
        menu = await role_menu_service.update_menu(guild_id, menu_id, data)
        return RoleMenuSchema.model_validate(menu)

    @delete(
        "/{menu_id:uuid}",
        operation_id="DeleteRoleMenu",
        summary="Delete a role menu",
        description="Deletes a role menu and its options.",
        response_description="The role menu was deleted.",
        responses={404: _NOT_FOUND},
    )
    async def delete_role_menu(
        self,
        guild_id: GuildIdPath,
        menu_id: Annotated[UUID, Parameter(description="The role menu's ID.")],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> None:
        await role_menu_service.delete_menu(guild_id, menu_id)

    @put(
        "/{menu_id:uuid}/options/{role_id:int}",
        operation_id="UpsertRoleMenuOption",
        summary="Add or edit a role menu option",
        description="Adds or edits the button for a Discord role on the menu. Returns the updated menu.",
        response_description="The updated role menu.",
        responses={
            404: _NOT_FOUND,
            400: ResponseSpec(None, description="The menu already has the maximum number of options."),
        },
    )
    async def upsert_role_menu_option(
        self,
        guild_id: GuildIdPath,
        menu_id: Annotated[UUID, Parameter(description="The role menu's ID.")],
        role_id: Annotated[int, Parameter(description="The Discord role ID the button grants.")],
        data: JSONBody[RoleMenuOptionUpsert],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> RoleMenuSchema:
        menu = await role_menu_service.upsert_option(guild_id, menu_id, role_id, data)
        return RoleMenuSchema.model_validate(menu)

    @delete(
        "/{menu_id:uuid}/options/{role_id:int}",
        operation_id="DeleteRoleMenuOption",
        status_code=200,
        summary="Remove a role menu option",
        description="Removes the button for a Discord role from the menu. Returns the updated menu.",
        response_description="The updated role menu.",
        responses={
            404: ResponseSpec(None, description="No role menu with that ID exists, or the role is not on the menu.")
        },
    )
    async def delete_role_menu_option(
        self,
        guild_id: GuildIdPath,
        menu_id: Annotated[UUID, Parameter(description="The role menu's ID.")],
        role_id: Annotated[int, Parameter(description="The Discord role ID the button grants.")],
        role_menu_service: NamedDependency[RoleMenuService],
    ) -> RoleMenuSchema:
        menu = await role_menu_service.delete_option(guild_id, menu_id, role_id)
        return RoleMenuSchema.model_validate(menu)
