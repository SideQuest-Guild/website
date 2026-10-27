"""Role menu + option persistence, scoped to a guild."""

from typing import TYPE_CHECKING

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import NotFoundException, ValidationException

from sidequest_common.models import RoleMenu, RoleMenuOption

if TYPE_CHECKING:
    from uuid import UUID

    from sidequest_common.schemas import RoleMenuCreate, RoleMenuOptionUpsert, RoleMenuUpdate

MAX_OPTIONS = 25
"""Discord allows at most 25 buttons on a single message."""


class RoleMenuRepository(SQLAlchemyAsyncRepository[RoleMenu]):
    """RoleMenu persistence."""

    model_type = RoleMenu


class RoleMenuService(SQLAlchemyAsyncRepositoryService[RoleMenu]):
    """Role menus and their options. Every lookup is scoped to a guild to keep cross-guild access out."""

    repository_type = RoleMenuRepository

    async def create_menu(self, guild_id: int, data: RoleMenuCreate) -> RoleMenu:
        """Create a menu with no options yet; the bot posts the message and PATCHes ``message_id``."""
        return await self.create(RoleMenu(guild_id=guild_id, **data.model_dump()), auto_commit=True)

    async def list_menus(self, guild_id: int) -> list[RoleMenu]:
        """All menus in the guild, options ordered by position (relationship ``order_by``)."""
        results, _ = await self.get_many_and_count(guild_id=guild_id)
        return list(results)

    async def get_menu(self, guild_id: int, menu_id: UUID) -> RoleMenu:
        """A menu scoped to ``guild_id``. Raises ``NotFoundException`` if it doesn't exist or belongs elsewhere."""
        menu = await self.get_one_or_none(id=menu_id, guild_id=guild_id)
        if menu is None:
            msg = f"Role menu {menu_id} not found"
            raise NotFoundException(msg)
        return menu

    async def update_menu(self, guild_id: int, menu_id: UUID, data: RoleMenuUpdate) -> RoleMenu:
        """Apply only the fields set on ``data``."""
        menu = await self.get_menu(guild_id, menu_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(menu, field, value)
        return await self.update(menu, auto_commit=True)

    async def delete_menu(self, guild_id: int, menu_id: UUID) -> None:
        """Delete a menu and its options (cascade)."""
        menu = await self.get_menu(guild_id, menu_id)
        await self.delete(menu.id, auto_commit=True)

    async def upsert_option(self, guild_id: int, menu_id: UUID, role_id: int, data: RoleMenuOptionUpsert) -> RoleMenu:
        """Add or edit the button for ``role_id``.

        New options append at the end (``position = len(options)``) unless ``data.position`` is given. Moving an
        existing option, or inserting a new one, always renumbers every option on the menu contiguously from 0 so
        positions never collide. Raises ``ValidationException`` past the 25-option cap.
        """
        menu = await self.get_menu(guild_id, menu_id)
        session = self.repository.session
        existing = next((option for option in menu.options if option.role_id == role_id), None)
        if existing is not None:
            existing.label = data.label
            existing.emoji = data.emoji
            existing.description = data.description
            if data.position is not None:
                others = [option for option in menu.options if option is not existing]
                self._place_option(existing, others, data.position)
        else:
            if len(menu.options) >= MAX_OPTIONS:
                msg = f"Role menu already has the maximum of {MAX_OPTIONS} options"
                raise ValidationException(msg)
            option = RoleMenuOption(
                role_menu_id=menu.id,
                role_id=role_id,
                label=data.label,
                emoji=data.emoji,
                description=data.description,
                position=0,
            )
            self._place_option(option, list(menu.options), data.position)
            session.add(option)
        await session.commit()
        await session.refresh(menu, attribute_names=["options"])
        return menu

    @staticmethod
    def _place_option(option: RoleMenuOption, others: list[RoleMenuOption], position: int | None) -> None:
        """Insert ``option`` among ``others`` at ``position`` (clamped), then renumber everyone 0..n contiguously."""
        ordered = sorted(others, key=lambda o: o.position)
        target = min(max(position, 0), len(ordered)) if position is not None else len(ordered)
        ordered.insert(target, option)
        for index, item in enumerate(ordered):
            item.position = index

    async def delete_option(self, guild_id: int, menu_id: UUID, role_id: int) -> RoleMenu:
        """Remove the button for ``role_id`` and re-pack remaining positions. Raises 404 if the role isn't on it."""
        menu = await self.get_menu(guild_id, menu_id)
        session = self.repository.session
        existing = next((option for option in menu.options if option.role_id == role_id), None)
        if existing is None:
            msg = f"Role {role_id} is not on role menu {menu_id}"
            raise NotFoundException(msg)
        await session.delete(existing)
        await session.flush()
        remaining = sorted((o for o in menu.options if o.role_id != role_id), key=lambda o: o.position)
        for index, option in enumerate(remaining):
            option.position = index
        await session.commit()
        await session.refresh(menu, attribute_names=["options"])
        return menu
