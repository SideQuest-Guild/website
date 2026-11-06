"""Battleground scoreboards recorded by members' addons. Members-only data: other players' names and stats included."""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime
from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class BattlegroundMatch(UUIDAuditBase):
    """One finished battleground, stored once however many members recorded it.

    ``external_id`` is the first recording's addon id. ``guild_faction`` is the side the recording member played on.
    """

    __tablename__ = "battleground_match"
    __table_args__ = {"comment": "Finished battlegrounds recorded by members' addons; one row per match."}

    external_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    map: Mapped[str] = mapped_column(Text)
    instance_id: Mapped[int] = mapped_column(Integer, index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    duration: Mapped[int] = mapped_column(Integer, default=0)
    winner: Mapped[str | None] = mapped_column(String(10), default=None)
    guild_faction: Mapped[str] = mapped_column(String(10))
    recorder: Mapped[str] = mapped_column(Text)


class BattlegroundScore(UUIDAuditBase):
    """One scoreboard row of a match. ``character_id`` links it to a guild character when the name matches one."""

    __tablename__ = "battleground_score"
    __table_args__ = {"comment": "Scoreboard rows of recorded battlegrounds, one per player per match."}

    match_id: Mapped[UUID] = mapped_column(ForeignKey("battleground_match.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("wow_character.id", ondelete="SET NULL"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(Text)
    faction: Mapped[str] = mapped_column(String(10))
    race: Mapped[str | None] = mapped_column(Text, default=None)
    wow_class: Mapped[str | None] = mapped_column(String(20), default=None)
    killing_blows: Mapped[int] = mapped_column(Integer, default=0)
    honorable_kills: Mapped[int] = mapped_column(Integer, default=0)
    deaths: Mapped[int] = mapped_column(Integer, default=0)
    honor_gained: Mapped[int] = mapped_column(Integer, default=0)
    damage_done: Mapped[int] = mapped_column(Integer, default=0)
    healing_done: Mapped[int] = mapped_column(Integer, default=0)
