"""EPGP loot system: WoW characters, raid sessions/encounters, loot awards, and the EP/GP ledger.

Source of truth is the site (``local://addon-contract.md``); the ``sidequest-sync`` addon exports raid facts and
ledger entries as an ``SQX1:`` string, an officer pastes it (or uploads SavedVariables) into
``POST /api/epgp/imports``, and the import service upserts by each record's addon-assigned ``external_id`` so
re-importing the same string is a no-op. GP/EP decay (15% per weekly reset) is never stored: it's applied on read
from ``EpgpLedgerEntry.at`` (see ``sidequest_api.domain.epgp.services``). A voided row (``voided_at`` set) is kept
forever and excluded from standings; it can never be un-voided.
"""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime
from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class WowCharacter(UUIDAuditBase):
    """One in-game character, keyed ``"name-realm"`` lowercase (case-insensitive match per the contract).

    ``member_id`` links the character to a site member, sharing that member's EP/GP balance; ``source`` records how
    the link happened (``claim``: the member self-claimed it on the account page; ``officer``: an officer set it on
    the characters admin screen; ``signup``: auto-linked because the name matched exactly one member's event sign-up
    character; ``import``: seen in an addon import with no link yet). ``is_main`` flags the character shown as a
    member's primary on standings.
    """

    __tablename__ = "wow_character"
    __table_args__ = {"comment": "In-game characters, auto-created from addon imports, optionally linked to a member."}

    name: Mapped[str] = mapped_column(Text)
    realm: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text, unique=True, index=True)
    wow_class: Mapped[str | None] = mapped_column(String(20), default=None)
    member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("member.id", ondelete="SET NULL"), index=True, default=None
    )
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="import")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)


class RaidSession(UUIDAuditBase):
    """One raid night, as recorded by the addon's session recorder and exported by ``id``.

    ``event_id`` links to the site's ``GuildEvent`` when the officer started it from a scheduled raid (drives the
    attendance hand-off); ``null`` for an ad-hoc session with no matching event. ``recorder`` is the officer
    character that exported the session, used for the one-recorder-per-raid-night conflict rule.
    """

    __tablename__ = "raid_session"
    __table_args__ = {"comment": "One raid night exported by the addon; conflicting re-recordings are skipped."}

    external_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("guild_event.id", ondelete="SET NULL"), index=True, default=None
    )
    instance_name: Mapped[str] = mapped_column(Text)
    instance_id: Mapped[int] = mapped_column(Integer, index=True)
    difficulty_id: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    recorder: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))


class SessionCharacterPresence(UUIDAuditBase):
    """One character's attendance window within one raid session, standby (bench) or not.

    Drives the attendance hand-off: every member linked to a session character (standby included, as bench) gets
    marked attended on the linked event's sign-up.
    """

    __tablename__ = "session_character_presence"
    __table_args__ = (
        UniqueConstraint("session_id", "character_id", name="uq_session_character_presence_session_character"),
        {"comment": "Per-character attendance window within one raid session."},
    )

    session_id: Mapped[UUID] = mapped_column(ForeignKey("raid_session.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[UUID] = mapped_column(ForeignKey("wow_character.id", ondelete="CASCADE"), index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    standby: Mapped[bool] = mapped_column(Boolean, default=False)


class Encounter(UUIDAuditBase):
    """One boss pull (or kill) within a raid session, for the loot log and the progression board.

    ``characters``/``standby`` are the addon-reported character keys present for the pull; kept as JSON rather than
    a join table since nothing queries them per-character (only the session's ``SessionCharacterPresence`` rows
    drive attendance and standings).
    """

    __tablename__ = "raid_encounter"
    __table_args__ = {"comment": "One boss pull within a raid session; feeds the loot log and progression board."}

    external_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("raid_session.id", ondelete="CASCADE"), index=True)
    encounter_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    difficulty_id: Mapped[int] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean)
    started_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True))
    characters: Mapped[list[str]] = mapped_column(JsonB, default=list)
    standby: Mapped[list[str]] = mapped_column(JsonB, default=list)


class LootAward(UUIDAuditBase):
    """One item awarded during a raid session, with the GP charge recorded as a twin ``EpgpLedgerEntry``.

    ``officer`` is the awarding officer's in-game character name (addon data, not a site member link).
    """

    __tablename__ = "loot_award"
    __table_args__ = {"comment": "One item awarded during a raid session."}

    external_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raid_session.id", ondelete="SET NULL"), index=True, default=None
    )
    encounter_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raid_encounter.id", ondelete="SET NULL"), index=True, default=None
    )
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    item_name: Mapped[str] = mapped_column(Text)
    quality: Mapped[int] = mapped_column(Integer)
    inv_type: Mapped[str] = mapped_column(String(30))
    character_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("wow_character.id", ondelete="SET NULL"), index=True, default=None
    )
    response: Mapped[str] = mapped_column(String(20))
    gp: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    officer: Mapped[str] = mapped_column(Text)
    voided_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), index=True, default=None)


class EpgpLedgerEntry(UUIDAuditBase):
    """One EP or GP change: an addon-exported award, a loot GP charge, or a site-made officer adjustment.

    ``external_id`` is ``null`` (and so excluded from the unique constraint's enforcement across site rows) for
    adjustments made directly on the site (``POST /api/epgp/adjustments``); addon-exported rows always carry it,
    and re-importing the same row is a no-op. ``character_id``/``member_id`` are both nullable: an addon row ties to
    the character that earned it (``member_id`` resolved through the character's link at read time for the
    ledger/standings), while a site adjustment ties directly to the target member with no character.
    """

    __tablename__ = "epgp_ledger_entry"
    __table_args__ = (
        UniqueConstraint("external_id", name="uq_epgp_ledger_entry_external_id"),
        {"comment": "One EP/GP change: addon award, loot GP charge, or site officer adjustment."},
    )

    external_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    kind: Mapped[str] = mapped_column(String(10))
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    character_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("wow_character.id", ondelete="SET NULL"), index=True, default=None
    )
    member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("member.id", ondelete="SET NULL"), index=True, default=None
    )
    loot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("loot_award.id", ondelete="SET NULL"), index=True, default=None
    )
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raid_session.id", ondelete="SET NULL"), index=True, default=None
    )
    at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    officer: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10))
    voided_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), index=True, default=None)


class EpgpSyncToken(UUIDAuditBase):
    """A long-lived bearer token for the ``sidequest-sync`` uploader, scoped to one member.

    ``token_hash`` is the sha256 hex digest of the token (format ``sqs_`` + 40 url-safe chars); the plaintext is
    shown to the officer once, at creation, and never stored. The import endpoint accepts the token only while its
    member still holds an officer role, checked at request time (not cached on the row).
    """

    __tablename__ = "epgp_sync_token"
    __table_args__ = {"comment": "Bearer tokens for the sidequest-sync uploader, one per officer-named token."}

    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("member.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)


class EpgpImportAudit(UUIDAuditBase):
    """One ``POST /api/epgp/imports`` call: who ran it, which addon recorder it came from, and what changed."""

    __tablename__ = "epgp_import_audit"
    __table_args__ = {"comment": "One EPGP import call: actor, addon recorder, and resulting row counts."}

    member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("member.id", ondelete="SET NULL"), index=True, default=None
    )
    recorder: Mapped[str] = mapped_column(Text)
    counts: Mapped[dict] = mapped_column(JsonB, default=dict)
