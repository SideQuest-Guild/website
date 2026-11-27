"""Member link status reporting for the bot's role and nickname sync."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from sqlalchemy import select

from sidequest_common.models import BattlenetCharacter, GuildRank, GuildRosterSnapshot, Member, WowCharacter

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _site_linked(session: AsyncSession) -> dict[int, set[int]]:
    """Blizzard character ids linked to each member on the site (self-claimed, by an officer, or from the addon)."""
    out: dict[int, set[int]] = {}
    statement = select(WowCharacter.member_id, WowCharacter.blizzard_id).where(
        WowCharacter.member_id.is_not(None), WowCharacter.blizzard_id.is_not(None)
    )
    for member_id, blizzard_id in (await session.execute(statement)).tuples():
        if member_id is not None and blizzard_id is not None:  # the WHERE guarantees it; the column types don't
            out.setdefault(member_id, set()).add(blizzard_id)
    return out


async def guild_characters(session: AsyncSession, members: list[Member]) -> dict[int, list[str]]:
    """Each member's roster characters as "Name Surname" (by ``Member.id``), the one that joined first leading.

    Characters on the Battle.net guild roster that their Battle.net account owns or that are linked to them on the
    site, ordered by ``joined_roster_at``. Members with none on the roster are left out.
    """
    rows = (
        await session.execute(
            select(
                BattlenetCharacter.blizzard_id,
                BattlenetCharacter.name,
                BattlenetCharacter.surname,
                BattlenetCharacter.joined_roster_at,
            ).where(BattlenetCharacter.in_roster.is_(True))
        )
    ).tuples()
    roster = {cid: (joined, f"{name} {surname}".strip()) for cid, name, surname, joined in rows}
    if not roster:
        return {}
    site_linked = await _site_linked(session)
    never = datetime.max.replace(tzinfo=UTC)
    out: dict[int, list[str]] = {}
    for member in members:
        ids = set(member.battlenet_character_ids or ()) | site_linked.get(member.id, set())
        found = sorted((roster[cid] for cid in ids if cid in roster), key=lambda c: (c[0] or never, c[1]))
        if found:
            out[member.id] = [name for _, name in found]
    return out


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
    """Reports every known member's sign-in and Battle.net link status, in-game guild ranks and roster characters."""

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
        site_linked = await _site_linked(session)

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

    async def guild_characters(self, members: list[Member]) -> dict[int, list[str]]:
        """``guild_characters`` for ``members`` (module function), on this service's session."""
        return await guild_characters(self.repository.session, members)

    async def mark_character_nick(self, discord_id: int) -> Member | None:
        """Record the bot's one nickname call for the member with ``discord_id`` (idempotent); None if unknown."""
        member = await self.get_one_or_none(discord_id=discord_id)
        if member is None:
            return None
        if member.character_nick_at is None:
            member.character_nick_at = datetime.now(UTC)
            member = await self.update(member, auto_commit=True)
        return member
