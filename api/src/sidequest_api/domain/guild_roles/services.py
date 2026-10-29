"""Discord role names persistence: a full wholesale replace per guild on every bot push."""

from typing import TYPE_CHECKING

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from sqlalchemy import delete

from sidequest_common.models import GuildRole

if TYPE_CHECKING:
    from sidequest_common.schemas import GuildRoleIn


class GuildRolesRepository(SQLAlchemyAsyncRepository[GuildRole]):
    """GuildRole persistence."""

    model_type = GuildRole


class GuildRolesService(SQLAlchemyAsyncRepositoryService[GuildRole]):
    """Replaces a guild's full role set wholesale."""

    repository_type = GuildRolesRepository

    async def replace_roles(self, guild_id: int, roles: list[GuildRoleIn]) -> None:
        """Delete the guild's stored roles and insert ``roles`` in their place."""
        session = self.repository.session
        await session.execute(delete(GuildRole).where(GuildRole.guild_id == guild_id))
        for role in roles:
            session.add(
                GuildRole(
                    guild_id=guild_id,
                    role_id=role.id,
                    name=role.name,
                    color=role.color,
                    position=role.position,
                    managed=role.managed,
                )
            )
        await session.commit()
