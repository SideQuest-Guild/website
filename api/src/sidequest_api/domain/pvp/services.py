"""Members-only PvP reads: the match history page, one match's full scoreboard, and the PvP boards.

Rows are guild-linked when ``BattlegroundScore.character_id`` is set (see ``EpgpService._import_battlegrounds``).
Boards total every guild-linked row across every recorded battleground, ten characters to a board.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from litestar.exceptions import NotFoundException
from sqlalchemy import case, func, select

from sidequest_common.models import BattlegroundMatch, BattlegroundScore, WowCharacter
from sidequest_common.schemas import (
    PVP_BOARD_SIZE,
    PVP_MATCHES_PAGE_SIZE,
    PvpBoardEntry,
    PvpBoards,
    PvpMatchDetail,
    PvpMatchPage,
    PvpMatchSummary,
    PvpPlayerRow,
    WowClass,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def _wow_class(value: str | None) -> WowClass | None:
    if value is None:
        return None
    try:
        return WowClass(value.lower())
    except ValueError:
        return None


def _won(*, guild_faction: str, winner: str | None) -> bool | None:
    if winner is None or winner == "draw":
        return None
    return winner == guild_faction


class PvpService:
    """Battleground match history and PvP boards for signed-in members."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _guild_players(self, match_ids: list[UUID]) -> dict[UUID, list[str]]:
        players: dict[UUID, list[str]] = {match_id: [] for match_id in match_ids}
        if not match_ids:
            return players
        statement = (
            select(BattlegroundScore.match_id, WowCharacter.name)
            .join(WowCharacter, BattlegroundScore.character_id == WowCharacter.id)
            .where(BattlegroundScore.match_id.in_(match_ids))
        )
        for match_id, name in (await self._session.execute(statement)).all():
            if name not in players[match_id]:
                players[match_id].append(name)
        for names in players.values():
            names.sort(key=str.casefold)
        return players

    def _summary(self, match: BattlegroundMatch, guild_players: list[str]) -> PvpMatchSummary:
        return PvpMatchSummary(
            id=match.id,
            map=match.map,
            ended_at=match.ended_at,
            duration=match.duration,
            winner=match.winner,
            guild_faction=match.guild_faction,
            won=_won(guild_faction=match.guild_faction, winner=match.winner),
            guild_players=guild_players,
            recorded_by=match.recorder,
        )

    async def list_matches(self, page: int) -> PvpMatchPage:
        """One page of the match history, newest first, ``PVP_MATCHES_PAGE_SIZE`` matches a page."""
        total = (await self._session.execute(select(func.count()).select_from(BattlegroundMatch))).scalar_one()
        page_count = max(1, math.ceil(total / PVP_MATCHES_PAGE_SIZE))
        offset = (page - 1) * PVP_MATCHES_PAGE_SIZE
        statement = (
            select(BattlegroundMatch)
            .order_by(BattlegroundMatch.ended_at.desc(), BattlegroundMatch.id.desc())
            .offset(offset)
            .limit(PVP_MATCHES_PAGE_SIZE)
        )
        matches = (await self._session.execute(statement)).scalars().all()
        guild_players = await self._guild_players([match.id for match in matches])
        return PvpMatchPage(
            page=page,
            page_count=page_count,
            matches=[self._summary(match, guild_players[match.id]) for match in matches],
        )

    async def get_match(self, match_id: UUID) -> PvpMatchDetail:
        """One match's full scoreboard, highest honorable kills first. 404 if there is no such match."""
        match = await self._session.get(BattlegroundMatch, match_id)
        if match is None:
            msg = f"No battleground {match_id}"
            raise NotFoundException(msg)
        statement = (
            select(BattlegroundScore, WowCharacter.slug)
            .outerjoin(WowCharacter, BattlegroundScore.character_id == WowCharacter.id)
            .where(BattlegroundScore.match_id == match.id)
            .order_by(BattlegroundScore.honorable_kills.desc())
        )
        rows = (await self._session.execute(statement)).all()
        players = [
            PvpPlayerRow(
                name=score.name,
                faction=score.faction,
                race=score.race,
                wow_class=_wow_class(score.wow_class),
                killing_blows=score.killing_blows,
                honorable_kills=score.honorable_kills,
                deaths=score.deaths,
                honor_gained=score.honor_gained,
                damage_done=score.damage_done,
                healing_done=score.healing_done,
                guild_member=score.character_id is not None,
                character_slug=slug,
            )
            for score, slug in rows
        ]
        guild_players = await self._guild_players([match.id])
        summary = self._summary(match, guild_players[match.id])
        return PvpMatchDetail(**summary.model_dump(), players=players)

    async def get_boards(self) -> PvpBoards:
        """Totals over every recorded battleground for SideQuest characters, ten to a board."""
        total = (await self._session.execute(select(func.count()).select_from(BattlegroundMatch))).scalar_one()
        statement = (
            select(
                WowCharacter.name,
                WowCharacter.wow_class,
                WowCharacter.slug,
                func.sum(case((BattlegroundScore.faction == BattlegroundMatch.winner, 1), else_=0)).label("wins"),
                func.sum(BattlegroundScore.honorable_kills).label("honorable_kills"),
                func.sum(BattlegroundScore.killing_blows).label("killing_blows"),
                func.sum(BattlegroundScore.honor_gained).label("honor_gained"),
                func.sum(BattlegroundScore.damage_done).label("damage_done"),
                func.sum(BattlegroundScore.healing_done).label("healing_done"),
            )
            .select_from(BattlegroundScore)
            .join(BattlegroundMatch, BattlegroundScore.match_id == BattlegroundMatch.id)
            .join(WowCharacter, BattlegroundScore.character_id == WowCharacter.id)
            .group_by(WowCharacter.id, WowCharacter.name, WowCharacter.wow_class, WowCharacter.slug)
        )
        rows = (await self._session.execute(statement)).all()

        def board(metric: str) -> list[PvpBoardEntry]:
            ranked = sorted(rows, key=lambda row: getattr(row, metric), reverse=True)[:PVP_BOARD_SIZE]
            return [
                PvpBoardEntry(
                    name=row.name,
                    wow_class=_wow_class(row.wow_class),
                    character_slug=row.slug,
                    value=getattr(row, metric),
                )
                for row in ranked
            ]

        return PvpBoards(
            matches=total,
            wins=board("wins"),
            honorable_kills=board("honorable_kills"),
            killing_blows=board("killing_blows"),
            honor_gained=board("honor_gained"),
            damage_done=board("damage_done"),
            healing_done=board("healing_done"),
        )
