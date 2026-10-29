"""Member profile persistence: the bot's continuous Discord-driven refresh of existing members."""

from typing import TYPE_CHECKING

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from sqlalchemy import select

from sidequest_common.models import Member

if TYPE_CHECKING:
    from sidequest_common.schemas import MemberProfileIn


class MemberProfilesRepository(SQLAlchemyAsyncRepository[Member]):
    """Member persistence for profile syncing."""

    model_type = Member


class MemberProfilesService(SQLAlchemyAsyncRepositoryService[Member]):
    """Applies the bot's periodic/event-driven Discord profile push, updating only existing members."""

    repository_type = MemberProfilesRepository

    async def sync_profiles(self, profiles: list[MemberProfileIn], departed_ids: list[int]) -> None:
        """Update existing members from ``profiles``/``departed_ids``; never creates rows, ignores unknown ids.

        ``profiles`` entries overwrite username/global_name/guild_nick/avatar_hash/roles and set
        ``is_guild_member=True``. ``departed_ids`` set ``is_guild_member=False``, clear ``guild_nick``, and empty
        ``roles``. Never touches ``last_login_at``, Battle.net fields, or ``roster_confirmed_at``.
        """
        discord_ids = [profile.discord_id for profile in profiles] + list(departed_ids)
        if not discord_ids:
            return
        session = self.repository.session
        statement = select(Member).where(Member.discord_id.in_(discord_ids))
        members_by_discord_id = {member.discord_id: member for member in (await session.execute(statement)).scalars()}
        for profile in profiles:
            member = members_by_discord_id.get(profile.discord_id)
            if member is None:
                continue
            member.username = profile.username
            member.global_name = profile.global_name
            member.guild_nick = profile.guild_nick
            member.avatar_hash = profile.avatar_hash
            member.roles = profile.roles
            member.is_guild_member = True
        for discord_id in departed_ids:
            member = members_by_discord_id.get(discord_id)
            if member is None:
                continue
            member.is_guild_member = False
            member.guild_nick = None
            member.roles = []
        await session.commit()
