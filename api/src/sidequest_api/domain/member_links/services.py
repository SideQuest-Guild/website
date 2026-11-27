"""Member link status reporting for the bot's role sync."""

from dataclasses import dataclass, field

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from sqlalchemy import select

from sidequest_common.models import BattlenetCharacter, GuildRank, GuildRosterSnapshot, Member, WowCharacter


@dataclass(frozen=True)
class MemberRanks:
    """The in-game guild ranks one member's characters hold right now, best (lowest rank index) first.

    ``all`` counts every roster character linked to the member: owned by their Battle.net account, or linked on the
    site (self-claimed, by an officer, or matched from the addon). ``battlenet`` counts only the characters their
    linked Battle.net account owns, which no addon upload or site link can fake.
    """

    all: list[str] = field(default_factory=list)
    battlenet: list[str] = field(default_factory=list)


class MemberLinksRepository(SQLAlchemyAsyncRepository[Member]):
    """Member persistence for link-status reporting."""

    model_type = Member


class MemberLinksService(SQLAlchemyAsyncRepositoryService[Member]):
    """Reports every known member's sign-in and Battle.net link status, and their in-game guild ranks."""

    repository_type = MemberLinksRepository

    async def list_links(self) -> list[Member]:
        """Every known member: signed in, or confirmed from Discord without ever signing in."""
        return list(await self.get_many())

    async def rank_names(self) -> dict[int, str]:
        """Guild rank names by rank index: the addon's rank list, then names seen on its roster rows for the rest."""
        session = self.repository.session
        names = dict(
            (
                await session.execute(
                    select(GuildRosterSnapshot.rank_index, GuildRosterSnapshot.rank).where(
                        GuildRosterSnapshot.rank != ""
                    )
                )
            )
            .tuples()
            .all()
        )
        names.update((await session.execute(select(GuildRank.rank_index, GuildRank.name))).tuples().all())
        return names

    async def member_ranks(self, members: list[Member]) -> dict[int, MemberRanks]:
        """Each member's in-game ranks (by ``Member.id``), from the Battle.net guild roster's rank per character.

        Who holds which rank index comes from Battle.net's roster (synced every 30 minutes); the index's name comes
        from the addon's rank list. Members with no character on the roster, or only ranks without a known name,
        are left out.
        """
        session = self.repository.session
        roster = dict(
            (
                await session.execute(
                    select(BattlenetCharacter.blizzard_id, BattlenetCharacter.guild_rank).where(
                        BattlenetCharacter.in_roster.is_(True), BattlenetCharacter.guild_rank.is_not(None)
                    )
                )
            )
            .tuples()
            .all()
        )
        if not roster:
            return {}
        names = await self.rank_names()
        site_linked: dict[int, set[int]] = {}
        statement = select(WowCharacter.member_id, WowCharacter.blizzard_id).where(
            WowCharacter.member_id.is_not(None), WowCharacter.blizzard_id.is_not(None)
        )
        for member_id, blizzard_id in (await session.execute(statement)).tuples():
            site_linked.setdefault(member_id, set()).add(blizzard_id)

        def ranks(character_ids: set[int]) -> list[str]:
            indices = sorted({roster[cid] for cid in character_ids if cid in roster})
            return [names[index] for index in indices if index in names]

        out: dict[int, MemberRanks] = {}
        for member in members:
            owned = set(member.battlenet_character_ids or ())
            found = MemberRanks(all=ranks(owned | site_linked.get(member.id, set())), battlenet=ranks(owned))
            if found.all:
                out[member.id] = found
        return out
