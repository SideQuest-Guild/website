"""Characters as Battle.net publishes them: the SideQuest roster, plus anyone looked up by name.

Forever has no realms: a character's address is its lowercase ``name-surname`` slug. Battle.net publishes a profile
only some time after the character logs out, so a roster member can have no profile yet (``profile_found`` false):
its row then carries only what the roster says (level, class, race, rank).
"""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import BigInteger, Boolean, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class BattlenetCharacter(UUIDAuditBase):
    """One character's Battle.net summary, and its character sheet as last fetched.

    ``in_roster`` marks a current member of the SideQuest guild, from the last roster sync; ``guild_rank`` is its
    roster rank (0 is the Guild Master). The summary columns (item level, honorable kills, PvP rank, achievement
    points, spec) feed the Hall of Heroes boards and raid readiness without opening ``sheet``, the full character
    page as ``CharacterSheet`` built it.
    """

    __tablename__ = "battlenet_character"
    __table_args__ = {"comment": "Battle.net character profiles: the guild roster and characters looked up by name."}

    slug: Mapped[str] = mapped_column(Text, unique=True, index=True)
    blizzard_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(Text)
    surname: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer)
    wow_class: Mapped[str | None] = mapped_column(Text, default=None)
    race: Mapped[str | None] = mapped_column(Text, default=None)
    faction: Mapped[str | None] = mapped_column(Text, default=None)
    guild_name: Mapped[str | None] = mapped_column(Text, default=None)
    guild_slug: Mapped[str | None] = mapped_column(Text, default=None)
    in_roster: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    guild_rank: Mapped[int | None] = mapped_column(Integer, default=None)
    joined_roster_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    left_roster_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    profile_found: Mapped[bool] = mapped_column(Boolean, default=False)
    item_level: Mapped[int | None] = mapped_column(Integer, default=None)
    achievement_points: Mapped[int | None] = mapped_column(Integer, default=None)
    honorable_kills: Mapped[int | None] = mapped_column(Integer, default=None)
    pvp_rank: Mapped[int | None] = mapped_column(Integer, default=None)
    spec: Mapped[str | None] = mapped_column(Text, default=None)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    sheet: Mapped[dict[str, object] | None] = mapped_column(JsonB, default=None)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), index=True, default=None)
    """When the profile was last asked for, found or not. ``None`` until the first try."""


class CharacterMilestone(UUIDAuditBase):
    """A roster character reaching a milestone level (40 or 60), queued for the bot to post to Discord.

    Written once per character and level, when a sync or a profile refresh first sees the character at or above the
    level after having stored it below. ``posted_at`` is set when the bot has posted it.
    """

    __tablename__ = "character_milestone"
    __table_args__ = (
        UniqueConstraint("slug", "level", name="uq_character_milestone_slug_level"),
        {"comment": "Roster characters reaching levels 40 and 60, queued for the Discord feed."},
    )

    slug: Mapped[str] = mapped_column(Text, index=True)
    name: Mapped[str] = mapped_column(Text)
    surname: Mapped[str] = mapped_column(Text)
    wow_class: Mapped[str | None] = mapped_column(Text, default=None)
    level: Mapped[int] = mapped_column(Integer)
    reached_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), index=True, default=None)
    discord_message_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
