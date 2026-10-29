"""Member persistence, Discord-driven upserts, and Battle.net linking."""

from datetime import UTC, datetime
from typing import Any

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import NotFoundException
from sqlalchemy import delete, update

from sidequest_api.lib.battlenet import BattleNetOAuthError
from sidequest_common.models import EventSignup, EventSignupActivity, Member, OfficerAudit


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

    async def link_battlenet(self, member: Member, *, account_id: int, battletag: str) -> Member:
        """Attach a Battle.net account to ``member``; relinking the same account refreshes the BattleTag.

        Raises ``BattleNetOAuthError("battlenet_taken")`` if another member already linked that account.
        """
        holder = await self.get_one_or_none(battlenet_id=account_id)
        if holder is not None and holder.id != member.id:
            msg = "That Battle.net account is linked to another member"
            taken = "battlenet_taken"
            raise BattleNetOAuthError(taken, msg)
        member.battlenet_id = account_id
        member.battletag = battletag
        member.battlenet_linked_at = datetime.now(UTC)
        return await self.update(member, auto_commit=True)

    async def unlink_battlenet(self, member: Member) -> Member:
        """Remove the member's Battle.net link."""
        member.battlenet_id = None
        member.battletag = None
        member.battlenet_linked_at = None
        return await self.update(member, auto_commit=True)

    async def delete_account(self, member: Member) -> None:
        """Permanently delete ``member`` and every row that belongs to them.

        Deletes event signups explicitly rather than relying on the database's ``ON DELETE CASCADE`` alone, so
        this holds regardless of whether the engine enforces foreign keys (e.g. SQLite in tests). Also deletes
        the member's sign-up activity (the GM console's sign-up log) and nulls any officer-audit rows they
        authored, keeping each row's ``actor_name`` snapshot.
        """
        session = self.repository.session
        await session.execute(delete(EventSignup).where(EventSignup.member_id == member.id))
        await session.execute(delete(EventSignupActivity).where(EventSignupActivity.discord_id == member.discord_id))
        await session.execute(
            update(OfficerAudit).where(OfficerAudit.actor_member_id == member.id).values(actor_member_id=None)
        )
        await self.delete(member.id, auto_commit=True)

    async def get_for_officer_action(self, member_id: int) -> Member:
        """``member_id``'s row. Raises ``NotFoundException`` if no such member has ever signed in."""
        member = await self.get_one_or_none(id=member_id)
        if member is None:
            msg = f"No member {member_id}"
            raise NotFoundException(msg)
        return member

    async def confirm_roster(self, member: Member) -> Member:
        """Mark ``member`` confirmed on the in-game guild roster. Idempotent: keeps the first confirmation time."""
        if member.roster_confirmed_at is None:
            member.roster_confirmed_at = datetime.now(UTC)
            return await self.update(member, auto_commit=True)
        return member

    async def unconfirm_roster(self, member: Member) -> Member:
        """Clear ``member``'s roster confirmation."""
        member.roster_confirmed_at = None
        return await self.update(member, auto_commit=True)
