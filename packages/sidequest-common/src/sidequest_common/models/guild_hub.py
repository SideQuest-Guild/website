"""Guild hub v2: roster snapshot, professions/recipes, bank log, announcements, recruiting, notes, news.

Backs the addon contract's v2 sections (``local://addon-contract-v2.md``): the ``SQX1:`` export's ``roster``,
``professions``, ``bank``, ``announcements``, ``recruits``, and ``member_notes`` arrays, read back through
``/api/guild/*`` and the officer recruiting/notes screens, and mirrored into the ``SQI1:`` game-import string.
``GuildNewsEvent`` is generated (not addon-sourced) at the moment each underlying event is recorded, so the news
feed has stable ids without re-deriving (and possibly reordering) them from other tables on every read.
"""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime
from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class GuildRosterSnapshot(UUIDAuditBase):
    """The latest ``GetGuildRosterInfo`` row for one character, upserted on every roster export.

    One row per character (``character_id`` unique): the addon only ever reports its latest sweep, not history.
    ``left_guild_at`` is set once a character goes 30 days without appearing in a roster export; never deleted.
    """

    __tablename__ = "guild_roster_snapshot"
    __table_args__ = {"comment": "Latest guild roster sweep row per character (upserted, one per character)."}

    character_id: Mapped[UUID] = mapped_column(
        ForeignKey("wow_character.id", ondelete="CASCADE"), unique=True, index=True
    )
    rank: Mapped[str] = mapped_column(Text, default="")
    rank_index: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    zone: Mapped[str] = mapped_column(Text, default="")
    last_seen_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    left_guild_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), index=True, default=None)


class CharacterProfession(UUIDAuditBase):
    """One character's scanned profession (e.g. Blacksmithing 150/150); ``recipes`` replaced wholesale on each scan."""

    __tablename__ = "character_profession"
    __table_args__ = (
        UniqueConstraint("character_id", "profession", name="uq_character_profession_character_profession"),
        {"comment": "Per-character profession skill, upserted on each addon profession scan."},
    )

    character_id: Mapped[UUID] = mapped_column(ForeignKey("wow_character.id", ondelete="CASCADE"), index=True)
    profession: Mapped[str] = mapped_column(String(40))
    skill: Mapped[int] = mapped_column(Integer, default=0)
    max_skill: Mapped[int] = mapped_column(Integer, default=0)
    scanned_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))


class ProfessionRecipe(UUIDAuditBase):
    """A known recipe, keyed by the game's recipe id (the contract's ``recipes[].id``), shared across characters."""

    __tablename__ = "profession_recipe"
    __table_args__ = {"comment": "One game recipe id, shared by every character/profession pair that knows it."}

    recipe_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(Text)
    item_id: Mapped[int | None] = mapped_column(Integer, default=None)


class CharacterRecipeLink(UUIDAuditBase):
    """Many-to-many: one character/profession pair knows one recipe."""

    __tablename__ = "character_recipe_link"
    __table_args__ = (
        UniqueConstraint("profession_id", "recipe_id", name="uq_character_recipe_link_profession_recipe"),
        {"comment": "Which character/profession pairs know which recipe."},
    )

    profession_id: Mapped[UUID] = mapped_column(ForeignKey("character_profession.id", ondelete="CASCADE"), index=True)
    recipe_id: Mapped[UUID] = mapped_column(ForeignKey("profession_recipe.id", ondelete="CASCADE"), index=True)


class GuildBankLogEntry(UUIDAuditBase):
    """One guild bank log row. ``external_id`` is the addon's deterministic hash (the game's log has no ids)."""

    __tablename__ = "guild_bank_log_entry"
    __table_args__ = {"comment": "Insert-only guild bank activity log, addon-sourced."}

    external_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    character_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("wow_character.id", ondelete="SET NULL"), index=True, default=None
    )
    kind: Mapped[str] = mapped_column(String(20))
    item_id: Mapped[int | None] = mapped_column(Integer, default=None)
    item_name: Mapped[str | None] = mapped_column(Text, default=None)
    count: Mapped[int] = mapped_column(Integer, default=0)
    money: Mapped[int] = mapped_column(Integer, default=0)
    tab: Mapped[int | None] = mapped_column(Integer, default=None)


class GuildAnnouncement(UUIDAuditBase):
    """One officer announcement.

    From the addon (``external_id`` set, ``discord: true`` queues it for the bot) or made directly on the site
    (``external_id`` ``None``, ``source="site"``).
    """

    __tablename__ = "guild_announcement"
    __table_args__ = {"comment": "Officer announcements, game- or site-sourced, optionally posted to Discord."}

    external_id: Mapped[str | None] = mapped_column(String(80), unique=True, index=True, default=None)
    text: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(10))
    discord: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    discord_message_id: Mapped[int | None] = mapped_column(BigInteger, default=None)


class GuildRecruit(UUIDAuditBase):
    """One recruiting candidate (officer-only data), upserted by the addon's ``id`` or created on the site."""

    __tablename__ = "guild_recruit"
    __table_args__ = {"comment": "Recruiting candidates and their officer checklist/status."}

    external_id: Mapped[str | None] = mapped_column(String(80), unique=True, index=True, default=None)
    character: Mapped[str] = mapped_column(Text)
    wow_class: Mapped[str | None] = mapped_column(String(20), default=None)
    status: Mapped[str] = mapped_column(String(20), default="applicant")
    note: Mapped[str | None] = mapped_column(Text, default=None)
    checklist: Mapped[dict] = mapped_column(JsonB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))


class RecruitVote(UUIDAuditBase):
    """One officer's vote on one recruit, upserted by ``(recruit, officer)``."""

    __tablename__ = "recruit_vote"
    __table_args__ = (
        UniqueConstraint("recruit_id", "officer", name="uq_recruit_vote_recruit_officer"),
        {"comment": "One officer's vote on one recruit, upserted per officer."},
    )

    recruit_id: Mapped[UUID] = mapped_column(ForeignKey("guild_recruit.id", ondelete="CASCADE"), index=True)
    officer: Mapped[str] = mapped_column(Text)
    vote: Mapped[str] = mapped_column(String(10))
    at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))


class MemberNote(UUIDAuditBase):
    """One officer note about a character, voidable, never deleted. ``member_id`` resolves via the character link."""

    __tablename__ = "member_note"
    __table_args__ = {"comment": "Officer notes about members/characters, addon-sourced and voidable."}

    external_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    character: Mapped[str] = mapped_column(Text)
    member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("member.id", ondelete="SET NULL"), index=True, default=None
    )
    note: Mapped[str] = mapped_column(Text)
    officer: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), index=True, default=None)


class GuildNewsEvent(UUIDAuditBase):
    """One news feed item, generated once when its source event is first recorded.

    ``source_key`` is a deterministic string built from the source row (e.g. ``"loot:<loot_id>"``,
    ``"level:<character_id>:<level>"``); its uniqueness makes re-importing the same addon data a no-op instead of
    duplicating news, and gives the addon a stable id (the row's own ``id``) across imports.
    """

    __tablename__ = "guild_news_event"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_guild_news_event_source_key"),
        {"comment": "Guild news feed; one row per source event, deduplicated by source_key."},
    )

    source_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    character: Mapped[str | None] = mapped_column(Text, default=None)
    item_id: Mapped[int | None] = mapped_column(Integer, default=None)
    quality: Mapped[int | None] = mapped_column(Integer, default=None)
