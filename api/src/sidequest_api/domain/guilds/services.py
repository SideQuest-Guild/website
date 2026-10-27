"""Guild configuration service."""

from typing import TYPE_CHECKING

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import ValidationException

from sidequest_common.models import GuildConfig

if TYPE_CHECKING:
    from sidequest_common.schemas import GuildConfigUpdate


class GuildConfigRepository(SQLAlchemyAsyncRepository[GuildConfig]):
    """GuildConfig persistence."""

    model_type = GuildConfig


class GuildConfigService(SQLAlchemyAsyncRepositoryService[GuildConfig]):
    """Reads and updates per-guild config, creating defaults on first access."""

    repository_type = GuildConfigRepository
    match_fields = ["guild_id"]

    async def get_or_create_config(self, guild_id: int) -> GuildConfig:
        """The guild's config, created with defaults if it doesn't exist yet."""
        existing = await self.get_one_or_none(guild_id=guild_id)
        if existing is not None:
            return existing
        try:
            return await self.create(GuildConfig(guild_id=guild_id), auto_commit=True)
        except IntegrityError:
            # Another request created it between our read and insert. The failed flush poisons the session's
            # transaction, so roll back before reading the winner's row.
            await self.repository.session.rollback()
            return await self.get_one(guild_id=guild_id)

    async def update_config(self, guild_id: int, data: GuildConfigUpdate) -> GuildConfig:
        """Apply the fields present in ``data`` to the guild's config."""
        config = await self.get_or_create_config(guild_id)
        changes = data.model_dump(exclude_unset=True)
        xp_min = changes.get("xp_min", config.xp_min)
        xp_max = changes.get("xp_max", config.xp_max)
        if xp_min > xp_max:
            msg = f"xp_min ({xp_min}) must be <= xp_max ({xp_max})"
            raise ValidationException(msg)
        for field, value in changes.items():
            setattr(config, field, value)
        return await self.update(config, auto_commit=True)
