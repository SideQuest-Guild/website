"""Guild hub v2 read/write service.

Reads for ``/api/guild/*`` (roster, crafters, news, bank, announcements) and the officer recruiting/notes screens,
plus the two writes those screens get (site announcements, recruit status/checklist/votes). The addon-sourced
import side (roster/professions/signups/bank/announcements/recruits/member_notes upserts) lives in
``sidequest_api.domain.epgp.services.EpgpService.import_payload``, which shares the character cache with the rest
of the ``SQX1:`` import. See ``local://addon-contract-v2.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from litestar.exceptions import NotFoundException
from sqlalchemy import func, or_, select

from sidequest_common.models import (
    CharacterDirectoryChar,
    CharacterDirectoryCooldowns,
    CharacterDirectoryMarket,
    CharacterDirectorySection,
    CharacterDirectoryStock,
    CharacterProfession,
    CharacterRecipeLink,
    GuildAnnouncement,
    GuildBankLogEntry,
    GuildNewsEvent,
    GuildRecruit,
    GuildRosterSnapshot,
    ItemName,
    Member,
    MemberNote,
    ProfessionRecipe,
    RecruitVote,
    WowCharacter,
)
from sidequest_common.schemas import (
    AnnouncementPostedResult,
    EpgpMemberNoteList,
    EpgpMemberNoteRow,
    EpgpRecruitList,
    EpgpRecruitRow,
    EpgpRecruitUpdate,
    EpgpRecruitVoteCreate,
    ExportRecruitVote,
    GuildAnnouncementCreate,
    GuildAnnouncementRow,
    GuildAnnouncementsPage,
    GuildBankPage,
    GuildBankRow,
    GuildBankTotals,
    GuildCrafterProfessionCount,
    GuildCrafterResult,
    GuildCrafterRow,
    GuildCrafters,
    GuildDirectory,
    GuildDirectoryCharacter,
    GuildDirectoryCooldown,
    GuildDirectoryFreshness,
    GuildDirectoryProfession,
    GuildDirectoryReputation,
    GuildMarket,
    GuildMarketBuyRow,
    GuildMarketRequestRow,
    GuildMarketSellRow,
    GuildNewsItem,
    GuildNewsPage,
    GuildRoster,
    GuildRosterCharacter,
    GuildRosterMember,
    GuildRosterUnlinked,
    GuildStock,
    GuildStockRow,
    PendingAnnouncement,
    PendingAnnouncementsPage,
    RecruitChecklist,
    WowClass,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

ANNOUNCEMENTS_PAGE_SIZE = 20
BANK_TOTALS_WINDOW_DAYS = 30
MAX_CRAFTER_RESULTS = 50


def _character_key(character: str) -> str:
    return character.strip().lower()


class GuildHubService:
    """Everything the guild hub read endpoints and officer recruiting/notes screens read or write."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Roster ------------------------------------------------------------------------------------------------

    async def get_roster(self) -> GuildRoster:
        """The current roster (characters with no ``left_guild_at``), alts grouped under their linked member."""
        snapshot_rows = (
            (
                await self._session.execute(
                    select(GuildRosterSnapshot).where(GuildRosterSnapshot.left_guild_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        if not snapshot_rows:
            return GuildRoster(taken_at=None, members=[], unlinked=[])
        snapshot_by_character = {row.character_id: row for row in snapshot_rows}
        characters = {
            character.id: character
            for character in (
                await self._session.execute(
                    select(WowCharacter).where(WowCharacter.id.in_(snapshot_by_character.keys()))
                )
            )
            .scalars()
            .all()
        }
        taken_at = max(row.updated_at for row in snapshot_rows)
        member_ids = {character.member_id for character in characters.values() if character.member_id is not None}
        members = (
            {
                member.id: member
                for member in (await self._session.execute(select(Member).where(Member.id.in_(member_ids))))
                .scalars()
                .all()
            }
            if member_ids
            else {}
        )
        chars_by_member: dict[int, list[WowCharacter]] = {}
        unlinked_rows: list[GuildRosterUnlinked] = []
        for character in characters.values():
            snapshot = snapshot_by_character[character.id]
            if character.member_id is not None:
                chars_by_member.setdefault(character.member_id, []).append(character)
            else:
                unlinked_rows.append(
                    GuildRosterUnlinked(
                        name=character.name,
                        wow_class=WowClass(character.wow_class) if character.wow_class else None,
                        level=snapshot.level,
                        rank=snapshot.rank,
                        last_seen_at=snapshot.last_seen_at,
                    )
                )
        roster_members: list[GuildRosterMember] = []
        for member_id, chars in chars_by_member.items():
            member = members.get(member_id)
            if member is None:
                continue
            chars_sorted = sorted(chars, key=lambda character: character.key)
            main_char = next((c for c in chars_sorted if c.is_main), chars_sorted[0])
            roster_members.append(
                GuildRosterMember(
                    member_id=member_id,
                    name=member.display_name,
                    rank=snapshot_by_character[main_char.id].rank,
                    raid_status=member.raid_status,
                    main=main_char.key,
                    characters=[
                        GuildRosterCharacter(
                            name=character.key,
                            wow_class=WowClass(character.wow_class) if character.wow_class else None,
                            level=snapshot_by_character[character.id].level,
                            zone=snapshot_by_character[character.id].zone,
                            last_seen_at=snapshot_by_character[character.id].last_seen_at,
                            is_main=character.is_main,
                        )
                        for character in chars_sorted
                    ],
                )
            )
        roster_members.sort(key=lambda row: row.name.casefold())
        unlinked_rows.sort(key=lambda row: row.name.casefold())
        return GuildRoster(taken_at=taken_at, members=roster_members, unlinked=unlinked_rows)

    # --- Crafters ------------------------------------------------------------------------------------------------

    async def get_crafters(self, *, q: str | None, profession: str | None) -> GuildCrafters:
        """Characters that know a recipe matching ``q`` (recipe or profession substring) / ``profession``."""
        statement = (
            select(ProfessionRecipe, CharacterProfession, WowCharacter)
            .join(CharacterRecipeLink, CharacterRecipeLink.recipe_id == ProfessionRecipe.id)
            .join(CharacterProfession, CharacterProfession.id == CharacterRecipeLink.profession_id)
            .join(WowCharacter, WowCharacter.id == CharacterProfession.character_id)
        )
        if profession:
            statement = statement.where(CharacterProfession.profession == profession)
        if q:
            pattern = f"%{q}%"
            statement = statement.where(
                or_(ProfessionRecipe.name.ilike(pattern), CharacterProfession.profession.ilike(pattern))
            )
        rows = (await self._session.execute(statement)).all()
        member_ids = {character.member_id for _, _, character in rows if character.member_id is not None}
        members = (
            {
                member.id: member
                for member in (await self._session.execute(select(Member).where(Member.id.in_(member_ids))))
                .scalars()
                .all()
            }
            if member_ids
            else {}
        )
        grouped: dict[int, GuildCrafterResult] = {}
        for recipe, character_profession, character in rows:
            result = grouped.get(recipe.recipe_id)
            if result is None:
                result = GuildCrafterResult(
                    recipe_id=recipe.recipe_id, recipe_name=recipe.name, item_id=recipe.item_id, crafters=[]
                )
                grouped[recipe.recipe_id] = result
            member = members.get(character.member_id) if character.member_id is not None else None
            result.crafters.append(
                GuildCrafterRow(
                    character=character.key,
                    member_id=character.member_id,
                    member_name=member.display_name if member else None,
                    profession=character_profession.profession,
                    skill=character_profession.skill,
                )
            )
        results = sorted(grouped.values(), key=lambda row: row.recipe_name.casefold())[:MAX_CRAFTER_RESULTS]
        profession_counts = (
            await self._session.execute(
                select(
                    CharacterProfession.profession, func.count(func.distinct(CharacterProfession.character_id))
                ).group_by(CharacterProfession.profession)
            )
        ).all()
        professions = [
            GuildCrafterProfessionCount(profession=name, crafters=count) for name, count in profession_counts
        ]
        return GuildCrafters(results=results, professions=professions)

    # --- Directory ---------------------------------------------------------------------------------------------

    async def get_directory(self) -> GuildDirectory:
        """Every character with directory data: professions, char basics, attunements, reputations, cooldowns.

        Professions come from the shared ``CharacterProfession`` table (fed by both the legacy flat import and
        the directory's ``prof`` section); ``char``/``cd`` come from their own per-character tables.
        """
        profession_rows = (
            (await self._session.execute(select(CharacterProfession).order_by(CharacterProfession.profession)))
            .scalars()
            .all()
        )
        char_rows = (await self._session.execute(select(CharacterDirectoryChar))).scalars().all()
        cd_rows = (await self._session.execute(select(CharacterDirectoryCooldowns))).scalars().all()
        freshness_rows = (await self._session.execute(select(CharacterDirectorySection))).scalars().all()

        professions_by_char: dict[UUID, list[GuildDirectoryProfession]] = {}
        for row in profession_rows:
            professions_by_char.setdefault(row.character_id, []).append(
                GuildDirectoryProfession(name=row.profession, skill=row.skill, max_skill=row.max_skill)
            )
        char_by_id = {row.character_id: row for row in char_rows}
        cd_by_id = {row.character_id: row for row in cd_rows}
        freshness_by_char: dict[UUID, dict[str, datetime]] = {}
        for row in freshness_rows:
            freshness_by_char.setdefault(row.character_id, {})[row.section] = row.at

        character_ids = set(professions_by_char) | set(char_by_id) | set(cd_by_id)
        if not character_ids:
            return GuildDirectory(characters=[])
        characters = {
            character.id: character
            for character in (
                await self._session.execute(select(WowCharacter).where(WowCharacter.id.in_(character_ids)))
            )
            .scalars()
            .all()
        }
        member_ids = {c.member_id for c in characters.values() if c.member_id is not None}
        members = (
            {
                member.id: member
                for member in (await self._session.execute(select(Member).where(Member.id.in_(member_ids))))
                .scalars()
                .all()
            }
            if member_ids
            else {}
        )
        rows: list[GuildDirectoryCharacter] = []
        for character_id in character_ids:
            character = characters.get(character_id)
            if character is None:
                continue
            member = members.get(character.member_id) if character.member_id is not None else None
            char_row = char_by_id.get(character_id)
            cd_row = cd_by_id.get(character_id)
            freshness = freshness_by_char.get(character_id, {})
            rows.append(
                GuildDirectoryCharacter(
                    character=character.key,
                    member_id=character.member_id,
                    member_name=member.display_name if member else None,
                    professions=sorted(professions_by_char.get(character_id, []), key=lambda p: p.name),
                    level=char_row.level if char_row else None,
                    wow_class=WowClass(char_row.wow_class) if char_row and char_row.wow_class else None,
                    race=char_row.race if char_row else None,
                    spec=char_row.spec if char_row else None,
                    item_level=char_row.item_level if char_row else None,
                    attunements=list(char_row.attunements) if char_row else [],
                    reputations=[GuildDirectoryReputation(**r) for r in char_row.reputations] if char_row else [],
                    cooldowns=[
                        GuildDirectoryCooldown(key=c["key"], ready_at=datetime.fromtimestamp(c["ready_at"], tz=UTC))
                        for c in (cd_row.cooldowns if cd_row else [])
                    ],
                    freshness=GuildDirectoryFreshness(
                        prof=freshness.get("prof"),
                        char=freshness.get("char"),
                        cd=freshness.get("cd"),
                        market=freshness.get("market"),
                        stock=freshness.get("stock"),
                    ),
                )
            )
        rows.sort(key=lambda row: row.character.casefold())
        return GuildDirectory(characters=rows)

    # --- Market ---------------------------------------------------------------------------------------------

    async def get_market(self) -> GuildMarket:
        """Everyone's sell/buy listings and open material requests, newest requests first, with item names."""
        rows = (await self._session.execute(select(CharacterDirectoryMarket))).scalars().all()
        if not rows:
            return GuildMarket(sell=[], buy=[], requests=[])
        character_ids = {row.character_id for row in rows}
        characters = {
            c.id: c
            for c in (await self._session.execute(select(WowCharacter).where(WowCharacter.id.in_(character_ids))))
            .scalars()
            .all()
        }
        member_ids = {c.member_id for c in characters.values() if c.member_id is not None}
        members = (
            {
                m.id: m
                for m in (await self._session.execute(select(Member).where(Member.id.in_(member_ids)))).scalars().all()
            }
            if member_ids
            else {}
        )
        item_ids = {entry["item_id"] for row in rows for entry in (*row.sell, *row.buy, *row.requests)}
        item_names = (
            {
                n.item_id: n.name
                for n in (await self._session.execute(select(ItemName).where(ItemName.item_id.in_(item_ids))))
                .scalars()
                .all()
            }
            if item_ids
            else {}
        )
        sell: list[GuildMarketSellRow] = []
        buy: list[GuildMarketBuyRow] = []
        requests: list[GuildMarketRequestRow] = []
        for row in rows:
            character = characters.get(row.character_id)
            if character is None:
                continue
            member = members.get(character.member_id) if character.member_id is not None else None
            member_name = member.display_name if member else None
            sell.extend(
                GuildMarketSellRow(
                    character=character.key,
                    member_name=member_name,
                    item_id=entry["item_id"],
                    item_name=item_names.get(entry["item_id"]),
                    price=entry.get("price"),
                    qty=entry["qty"],
                    crafted=entry.get("crafted", False),
                )
                for entry in row.sell
            )
            buy.extend(
                GuildMarketBuyRow(
                    character=character.key,
                    member_name=member_name,
                    item_id=entry["item_id"],
                    item_name=item_names.get(entry["item_id"]),
                    price=entry.get("price"),
                )
                for entry in row.buy
            )
            requests.extend(
                GuildMarketRequestRow(
                    id=entry["id"],
                    character=character.key,
                    member_name=member_name,
                    item_id=entry["item_id"],
                    item_name=item_names.get(entry["item_id"]),
                    qty=entry["qty"],
                    price=entry.get("price"),
                    note=entry.get("note"),
                    at=datetime.fromtimestamp(entry["at"], tz=UTC),
                )
                for entry in row.requests
            )
        sell.sort(key=lambda r: (r.item_name or "").casefold())
        buy.sort(key=lambda r: (r.item_name or "").casefold())
        requests.sort(key=lambda r: r.at, reverse=True)
        return GuildMarket(sell=sell, buy=buy, requests=requests)

    # --- Stock ---------------------------------------------------------------------------------------------

    async def get_stock(self, item_id: int) -> GuildStock:
        """Who holds ``item_id`` in bags or bank, characters with none of it excluded."""
        rows = (await self._session.execute(select(CharacterDirectoryStock))).scalars().all()
        item_name_row = (
            await self._session.execute(select(ItemName).where(ItemName.item_id == item_id))
        ).scalar_one_or_none()
        character_ids = {row.character_id for row in rows}
        characters = (
            {
                c.id: c
                for c in (await self._session.execute(select(WowCharacter).where(WowCharacter.id.in_(character_ids))))
                .scalars()
                .all()
            }
            if character_ids
            else {}
        )
        member_ids = {c.member_id for c in characters.values() if c.member_id is not None}
        members = (
            {
                m.id: m
                for m in (await self._session.execute(select(Member).where(Member.id.in_(member_ids)))).scalars().all()
            }
            if member_ids
            else {}
        )
        result_rows: list[GuildStockRow] = []
        for row in rows:
            bags_count = sum(count for stored_id, count in row.bags if stored_id == item_id)
            bank_count = sum(count for stored_id, count in row.bank if stored_id == item_id)
            if bags_count == 0 and bank_count == 0:
                continue
            character = characters.get(row.character_id)
            if character is None:
                continue
            member = members.get(character.member_id) if character.member_id is not None else None
            result_rows.append(
                GuildStockRow(
                    character=character.key,
                    member_name=member.display_name if member else None,
                    bags=bags_count,
                    bank=bank_count,
                    bank_at=row.bank_at,
                )
            )
        result_rows.sort(key=lambda r: r.character.casefold())
        return GuildStock(item_id=item_id, item_name=item_name_row.name if item_name_row else None, rows=result_rows)

    # --- News ------------------------------------------------------------------------------------------------

    async def get_news(self, *, limit: int) -> GuildNewsPage:
        """Guild news feed, newest first."""
        rows = (
            (await self._session.execute(select(GuildNewsEvent).order_by(GuildNewsEvent.at.desc()).limit(limit)))
            .scalars()
            .all()
        )
        return GuildNewsPage(
            items=[
                GuildNewsItem(
                    id=row.id,
                    at=row.at,
                    kind=row.kind,
                    text=row.text,
                    character=row.character,
                    item_id=row.item_id,
                    quality=row.quality,
                )
                for row in rows
            ]
        )

    # --- Bank ------------------------------------------------------------------------------------------------

    async def get_bank(self, *, limit: int, before: datetime | None) -> GuildBankPage:
        """Guild bank log rows newest first, with 30-day deposit/withdrawal totals."""
        statement = select(GuildBankLogEntry)
        if before is not None:
            statement = statement.where(GuildBankLogEntry.at < before)
        rows = (
            (await self._session.execute(statement.order_by(GuildBankLogEntry.at.desc()).limit(limit))).scalars().all()
        )
        character_ids = {row.character_id for row in rows if row.character_id is not None}
        characters = (
            {
                character.id: character
                for character in (
                    await self._session.execute(select(WowCharacter).where(WowCharacter.id.in_(character_ids)))
                )
                .scalars()
                .all()
            }
            if character_ids
            else {}
        )
        member_ids = {character.member_id for character in characters.values() if character.member_id is not None}
        members = (
            {
                member.id: member
                for member in (await self._session.execute(select(Member).where(Member.id.in_(member_ids))))
                .scalars()
                .all()
            }
            if member_ids
            else {}
        )
        page_rows = []
        for row in rows:
            character = characters.get(row.character_id) if row.character_id is not None else None
            member = members.get(character.member_id) if character and character.member_id is not None else None
            page_rows.append(
                GuildBankRow(
                    id=row.id,
                    at=row.at,
                    character=character.key if character else None,
                    member_name=member.display_name if member else None,
                    kind=row.kind,
                    item_id=row.item_id,
                    item_name=row.item_name,
                    count=row.count,
                    money=row.money,
                    tab=row.tab,
                )
            )
        cutoff = datetime.now(UTC) - timedelta(days=BANK_TOTALS_WINDOW_DAYS)
        totals_rows = (
            await self._session.execute(
                select(GuildBankLogEntry.kind, GuildBankLogEntry.count).where(GuildBankLogEntry.at >= cutoff)
            )
        ).all()
        deposits = sum(count for kind, count in totals_rows if kind == "deposit")
        withdrawals = sum(count for kind, count in totals_rows if kind == "withdraw")
        return GuildBankPage(rows=page_rows, totals=GuildBankTotals(deposits_30d=deposits, withdrawals_30d=withdrawals))

    # --- Announcements ------------------------------------------------------------------------------------------

    async def get_announcements(self) -> GuildAnnouncementsPage:
        """The last 20 announcements, game- or site-sourced, newest first."""
        rows = (
            (
                await self._session.execute(
                    select(GuildAnnouncement).order_by(GuildAnnouncement.at.desc()).limit(ANNOUNCEMENTS_PAGE_SIZE)
                )
            )
            .scalars()
            .all()
        )
        return GuildAnnouncementsPage(
            items=[
                GuildAnnouncementRow(
                    id=row.id, text=row.text, author=row.author, at=row.at, source=row.source, posted_at=row.posted_at
                )
                for row in rows
            ]
        )

    async def create_announcement(self, data: GuildAnnouncementCreate, actor: Member) -> GuildAnnouncementRow:
        """A site-made announcement, attributed to ``actor``'s display name; also queued for Discord if asked."""
        now = datetime.now(UTC)
        row = GuildAnnouncement(text=data.text, author=actor.display_name, at=now, source="site", discord=data.discord)
        self._session.add(row)
        await self._session.flush()
        self._session.add(
            GuildNewsEvent(source_key=f"announcement:{row.id}", kind="announcement", text=row.text[:500], at=now)
        )
        await self._session.commit()
        return GuildAnnouncementRow(
            id=row.id, text=row.text, author=row.author, at=row.at, source=row.source, posted_at=row.posted_at
        )

    # --- Bot: pending announcements ------------------------------------------------------------------------------

    async def list_pending_announcements(self) -> PendingAnnouncementsPage:
        """Discord-queued announcements not yet posted, oldest first."""
        rows = (
            (
                await self._session.execute(
                    select(GuildAnnouncement)
                    .where(GuildAnnouncement.discord.is_(True), GuildAnnouncement.posted_at.is_(None))
                    .order_by(GuildAnnouncement.at)
                )
            )
            .scalars()
            .all()
        )
        return PendingAnnouncementsPage(
            items=[PendingAnnouncement(id=row.id, text=row.text, author=row.author, at=row.at) for row in rows]
        )

    async def mark_announcement_posted(self, announcement_id: UUID, message_id: int) -> AnnouncementPostedResult:
        """Record that ``announcement_id`` posted to Discord as ``message_id``, so it stops being pending."""
        row = await self._session.get(GuildAnnouncement, announcement_id)
        if row is None:
            msg = f"No announcement {announcement_id}"
            raise NotFoundException(msg)
        row.posted_at = datetime.now(UTC)
        row.discord_message_id = message_id
        await self._session.commit()
        return AnnouncementPostedResult(message_id=message_id)

    # --- Officer: recruits ---------------------------------------------------------------------------------------

    async def _to_recruit_row(self, recruit: GuildRecruit) -> EpgpRecruitRow:
        votes = (
            (await self._session.execute(select(RecruitVote).where(RecruitVote.recruit_id == recruit.id)))
            .scalars()
            .all()
        )
        character = (
            await self._session.execute(
                select(WowCharacter).where(WowCharacter.key == _character_key(recruit.character))
            )
        ).scalar_one_or_none()
        return EpgpRecruitRow(
            id=recruit.id,
            character=recruit.character,
            wow_class=WowClass(recruit.wow_class) if recruit.wow_class else None,
            status=recruit.status,
            note=recruit.note,
            checklist=RecruitChecklist.model_validate(recruit.checklist),
            votes=[
                ExportRecruitVote(officer=vote.officer, vote=vote.vote, at=int(vote.at.timestamp())) for vote in votes
            ],
            member_id=character.member_id if character else None,
            at=recruit.at,
        )

    async def list_recruits(self) -> EpgpRecruitList:
        """Every recruiting candidate, newest first."""
        rows = (await self._session.execute(select(GuildRecruit).order_by(GuildRecruit.at.desc()))).scalars().all()
        return EpgpRecruitList(recruits=[await self._to_recruit_row(row) for row in rows])

    async def update_recruit(self, recruit_id: UUID, data: EpgpRecruitUpdate) -> EpgpRecruitRow:
        """Update a recruit's status/note/checklist (only fields present). 404 unknown recruit.

        Setting ``status: "trial"`` also sets the linked member's ``raid_status``/``trial_started_at`` if the
        character is linked and the member has no raid status yet.
        """
        recruit = await self._session.get(GuildRecruit, recruit_id)
        if recruit is None:
            msg = f"No recruit {recruit_id}"
            raise NotFoundException(msg)
        changes = data.model_dump(exclude_unset=True)
        if "status" in changes and changes["status"] is not None:
            recruit.status = changes["status"]
        if "note" in changes:
            recruit.note = changes["note"]
        if "checklist" in changes and changes["checklist"] is not None:
            recruit.checklist = changes["checklist"]
        if recruit.status == "trial":
            character = (
                await self._session.execute(
                    select(WowCharacter).where(WowCharacter.key == _character_key(recruit.character))
                )
            ).scalar_one_or_none()
            if character is not None and character.member_id is not None:
                member = await self._session.get(Member, character.member_id)
                if member is not None and member.raid_status is None:
                    member.raid_status = "trial"
                    member.trial_started_at = datetime.now(UTC)
        await self._session.commit()
        return await self._to_recruit_row(recruit)

    async def add_recruit_vote(self, recruit_id: UUID, data: EpgpRecruitVoteCreate, actor: Member) -> EpgpRecruitRow:
        """Upsert ``actor``'s vote on ``recruit_id``. 404 unknown recruit."""
        recruit = await self._session.get(GuildRecruit, recruit_id)
        if recruit is None:
            msg = f"No recruit {recruit_id}"
            raise NotFoundException(msg)
        existing = (
            await self._session.execute(
                select(RecruitVote).where(
                    RecruitVote.recruit_id == recruit_id, RecruitVote.officer == actor.display_name
                )
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is None:
            self._session.add(RecruitVote(recruit_id=recruit_id, officer=actor.display_name, vote=data.vote, at=now))
        else:
            existing.vote = data.vote
            existing.at = now
        await self._session.commit()
        return await self._to_recruit_row(recruit)

    # --- Officer: member notes -------------------------------------------------------------------------------------

    async def list_member_notes(self, *, member_id: int | None) -> EpgpMemberNoteList:
        """Officer notes, optionally filtered to one member, newest first."""
        statement = select(MemberNote)
        if member_id is not None:
            statement = statement.where(MemberNote.member_id == member_id)
        rows = (await self._session.execute(statement.order_by(MemberNote.at.desc()))).scalars().all()
        return EpgpMemberNoteList(
            notes=[
                EpgpMemberNoteRow(
                    id=row.id,
                    character=row.character,
                    member_id=row.member_id,
                    note=row.note,
                    officer=row.officer,
                    at=row.at,
                    voided=row.voided_at is not None,
                )
                for row in rows
            ]
        )
