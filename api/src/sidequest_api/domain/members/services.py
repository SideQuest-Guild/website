"""Member persistence and Discord-driven upserts."""

from datetime import UTC, datetime
from typing import Any

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService

from sidequest_common.models import Member


class MembersRepository(SQLAlchemyAsyncRepository[Member]):
    """Member persistence."""

    model_type = Member


class MembersService(SQLAlchemyAsyncRepositoryService[Member]):
    """Looks up and upserts members from their Discord profile."""

    repository_type = MembersRepository

    async def upsert_from_discord(self, user: dict[str, Any], guild_member: dict[str, Any] | None) -> Member:
        """Create or refresh the Member row for a Discord user that just completed OAuth login.

        ``guild_member`` is Discord's ``/users/@me/guilds/{guild_id}/member`` response, or ``None`` if the user
        isn't in the guild. Roles/nick/membership are always overwritten with the latest values from Discord.
        """
        discord_id = int(user["id"])
        member = await self.get_one_or_none(discord_id=discord_id)
        is_guild_member = guild_member is not None
        guild_nick = guild_member.get("nick") if guild_member else None
        roles = [int(role_id) for role_id in guild_member.get("roles", [])] if guild_member else []
        now = datetime.now(UTC)
        fields = {
            "discord_id": discord_id,
            "username": user["username"],
            "global_name": user.get("global_name"),
            "avatar_hash": user.get("avatar"),
            "guild_nick": guild_nick,
            "roles": roles,
            "is_guild_member": is_guild_member,
            "last_login_at": now,
        }
        if member is None:
            return await self.create(Member(**fields), auto_commit=True)
        for field, value in fields.items():
            setattr(member, field, value)
        return await self.update(member, auto_commit=True)
