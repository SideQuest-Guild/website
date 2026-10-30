"""EPGP loot system services.

The ``SQX1:`` import, decayed-on-read standings, ledger/loot/progression reads, the ``SQI1:`` game-import string,
officer adjustments/characters/roster/sync-tokens, and member self-service characters. See
``local://addon-contract.md``. Decay is never stored: every read applies ``AMOUNT * 0.85 ** resets`` from
``EpgpLedgerEntry.at`` to "now" (weekly resets land Tuesday 15:00 UTC).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from litestar.exceptions import HTTPException, NotFoundException, ValidationException
from litestar.status_codes import HTTP_409_CONFLICT
from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select

from sidequest_common.models import (
    CharacterProfession,
    CharacterRecipeLink,
    Encounter,
    EpgpImportAudit,
    EpgpLedgerEntry,
    EpgpSyncToken,
    EventSignup,
    GuildAnnouncement,
    GuildBankLogEntry,
    GuildEvent,
    GuildNewsEvent,
    GuildRecruit,
    GuildRosterSnapshot,
    LootAward,
    Member,
    MemberBadge,
    MemberNote,
    ProfessionRecipe,
    RaidSession,
    RecruitVote,
    SessionCharacterPresence,
    WowCharacter,
)
from sidequest_common.schemas import (
    BADGES,
    BASE_GP,
    CHASE_MULTIPLIER,
    DECAY_PERCENT,
    DEFAULT_REALM,
    EP_VALUES,
    EPGP_RULES,
    GP_BY_INVTYPE,
    INACTIVE_AFTER_DAYS,
    LEFT_GUILD_AFTER_DAYS,
    LEGENDARY_GP,
    LEVEL_MILESTONE_STEP,
    MAX_IMPORT_BYTES,
    MIN_GP,
    OS_PERCENT,
    TRIAL_DAYS,
    WEEKLY_RESET_HOUR_UTC,
    WEEKLY_RESET_WEEKDAY,
    AnnouncementImportCounts,
    AwardImportCounts,
    BankImportCounts,
    CharacterSource,
    EpgpAdjustmentCreate,
    EpgpCharacter,
    EpgpCharacterList,
    EpgpCharacterUpdate,
    EpgpGameImport,
    EpgpImportResult,
    EpgpLedgerPage,
    EpgpLedgerRow,
    EpgpLootPage,
    EpgpLootRow,
    EpgpProgression,
    EpgpProgressionEncounter,
    EpgpProgressionInstance,
    EpgpRoster,
    EpgpRosterRow,
    EpgpRosterUpdate,
    EpgpRules,
    EpgpStandings,
    EpgpStandingsRow,
    EpgpSyncTokenCreate,
    EpgpSyncTokenCreated,
    EpgpSyncTokenList,
    EpgpSyncTokenSummary,
    EventKind,
    ExportPayload,
    ExportRecruitVote,
    GameImportBadgeRef,
    GameImportCharacter,
    GameImportCrafter,
    GameImportEvent,
    GameImportInactiveMember,
    GameImportLedgerEntry,
    GameImportLootEntry,
    GameImportMember,
    GameImportNews,
    GameImportOfficerNote,
    GameImportOfficerPart,
    GameImportOfficerRecruit,
    GameImportPayload,
    GameImportSheet,
    GameImportSignup,
    GameImportStandingsRow,
    ImportAttendanceResult,
    ImportCounts,
    LedgerKind,
    LootImportCounts,
    LootResponse,
    MemberNoteImportCounts,
    MyCharacterCreate,
    ProfessionImportCounts,
    RaidStatus,
    RecruitChecklist,
    RecruitImportCounts,
    RosterImportCounts,
    SignupImportCounts,
    SignupRole,
    SignupStatus,
    WowClass,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from sidequest_common.schemas import (
        ExportAnnouncement,
        ExportBankEntry,
        ExportMemberNote,
        ExportProfession,
        ExportRecruit,
        ExportRoster,
        ExportSignupV2,
    )

EXPORT_PREFIX = "SQX1:"
IMPORT_PREFIX = "SQI1:"
_EXPORT_STRING_RE = re.compile(r"SQX1:([A-Za-z0-9+/=]+)")
_GAME_IMPORT_WINDOW_BEFORE = timedelta(hours=6)
_GAME_IMPORT_WINDOW_AFTER = timedelta(days=14)
_ROLE_KINDS = ("raid", "dungeon")
_TOKEN_ALPHABET = string.ascii_letters + string.digits + "-_"
_TOKEN_PREFIX = "sqs_"  # noqa: S105 - not a password, a public token format prefix
_TOKEN_RANDOM_LENGTH = 40


def _reset_boundary_on_or_before(moment: datetime) -> datetime:
    """The most recent weekly reset instant (Tuesday 15:00 UTC) at or before ``moment``."""
    days_since = (moment.weekday() - WEEKLY_RESET_WEEKDAY) % 7
    candidate = (moment - timedelta(days=days_since)).replace(
        hour=WEEKLY_RESET_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    if candidate > moment:
        candidate -= timedelta(days=7)
    return candidate


def resets_since(at: datetime, now: datetime) -> int:
    """How many weekly resets have landed strictly between ``at`` and ``now``."""
    if now <= at:
        return 0
    last_before_now = _reset_boundary_on_or_before(now)
    last_before_at = _reset_boundary_on_or_before(at)
    if last_before_now <= last_before_at:
        return 0
    return (last_before_now - last_before_at).days // 7


def decayed_amount(amount: int, at: datetime, now: datetime) -> float:
    """``amount`` after applying ``DECAY_PERCENT`` weekly decay for every reset since ``at``."""
    return amount * ((1 - DECAY_PERCENT / 100) ** resets_since(at, now))


def _character_key(character: str) -> str:
    return character.strip().lower()


class EpgpService:
    """Everything the EPGP domain reads or writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """The request's session."""
        return self._session

    # --- Import: SQX1: parsing -------------------------------------------------------------------------------

    def _decode_payload(self, raw_text: str) -> ExportPayload:
        match = _EXPORT_STRING_RE.search(raw_text)
        if match is None:
            msg = "No SQX1: export string found in payload"
            raise ValidationException(msg)
        try:
            decoded = base64.b64decode(match.group(1), validate=True)
        except binascii.Error as exc:
            msg = "SQX1: export string is not valid base64"
            raise ValidationException(msg) from exc
        if len(decoded) > MAX_IMPORT_BYTES:
            msg = f"Decoded export payload exceeds {MAX_IMPORT_BYTES} bytes"
            raise ValidationException(msg)
        try:
            data = json.loads(decoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            msg = "SQX1: export string does not decode to JSON"
            raise ValidationException(msg) from exc
        try:
            payload = ExportPayload.model_validate(data)
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(part) for part in first["loc"])
            msg = f"Invalid export payload at {loc or '<root>'}: {first['msg']}"
            raise ValidationException(msg) from exc
        if payload.v not in (1, 2):
            msg = f"Unsupported export payload version {payload.v}"
            raise ValidationException(msg)
        return payload

    async def _get_or_create_character(
        self, cache: dict[str, WowCharacter], character: str, wow_class: str | None, seen_at: datetime
    ) -> WowCharacter:
        key = _character_key(character)
        row = cache.get(key)
        if row is None:
            row = (
                await self._session.execute(select(WowCharacter).where(WowCharacter.key == key))
            ).scalar_one_or_none()
            if row is None:
                name, _, realm = character.rpartition("-")
                if not name:
                    name, realm = character, ""
                row = WowCharacter(name=name, realm=realm, key=key, source="import")
                self._session.add(row)
                await self._session.flush()
                await self._auto_link_character(row)
            cache[key] = row
        if wow_class is not None:
            row.wow_class = wow_class
        if row.last_seen_at is None or seen_at > row.last_seen_at:
            row.last_seen_at = seen_at
        return row

    async def _auto_link_character(self, character: WowCharacter) -> None:
        """Link ``character`` to a member when its name matches exactly one member's sign-up character."""
        if character.member_id is not None:
            return
        statement = select(EventSignup.member_id, EventSignup.character).where(EventSignup.character.is_not(None))
        candidate_ids = {
            member_id
            for member_id, signup_character in (await self._session.execute(statement)).all()
            if signup_character is not None and signup_character.strip().lower() == character.name.strip().lower()
        }
        if len(candidate_ids) == 1:
            character.member_id = next(iter(candidate_ids))
            character.source = "signup"

    async def _conflicting_session(
        self, *, instance_id: int, started_at: datetime, ended_at: datetime, recorder: str, external_id: str
    ) -> bool:
        statement = (
            select(RaidSession.id)
            .where(
                RaidSession.instance_id == instance_id,
                RaidSession.recorder != recorder,
                RaidSession.external_id != external_id,
                RaidSession.started_at < ended_at,
                RaidSession.ended_at > started_at,
            )
            .limit(1)
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def _session_internal_id(self, session_id_map: dict[str, UUID | None], external_id: str) -> UUID | None:
        if external_id in session_id_map:
            return session_id_map[external_id]
        row_id = (
            await self._session.execute(select(RaidSession.id).where(RaidSession.external_id == external_id))
        ).scalar_one_or_none()
        session_id_map[external_id] = row_id
        return row_id

    async def import_payload(  # noqa: C901, PLR0912, PLR0915 - one linear upsert pass per contract section
        self, raw_text: str, actor: Member
    ) -> EpgpImportResult:
        """Decode, validate, and upsert one ``SQX1:`` export string. Readable ``ValidationException`` on bad input.

        Idempotent by each record's ``external_id``: re-importing the same string creates no new rows. Sessions
        that conflict with a different recorder's overlapping session (same ``instance_id``) are skipped, along
        with their encounters/loot/awards, and listed in the result's ``conflicts``.
        """
        payload = self._decode_payload(raw_text)
        character_cache: dict[str, WowCharacter] = {}

        session_counts = ImportCounts()
        session_id_map: dict[str, UUID | None] = {}
        conflicts: list[str] = []
        for entry in payload.sessions:
            started_at = datetime.fromtimestamp(entry.started_at, tz=UTC)
            ended_at = datetime.fromtimestamp(entry.ended_at, tz=UTC) if entry.ended_at is not None else started_at
            if await self._conflicting_session(
                instance_id=entry.instance_id,
                started_at=started_at,
                ended_at=ended_at,
                recorder=payload.recorder,
                external_id=entry.id,
            ):
                conflicts.append(entry.id)
                session_id_map[entry.id] = None
                continue
            existing = (
                await self._session.execute(select(RaidSession).where(RaidSession.external_id == entry.id))
            ).scalar_one_or_none()
            is_new = existing is None
            row = existing or RaidSession(external_id=entry.id)
            row.event_id = entry.event_id
            row.instance_name = entry.instance_name
            row.instance_id = entry.instance_id
            row.difficulty_id = entry.difficulty_id
            row.size = entry.size
            row.recorder = payload.recorder
            row.started_at = started_at
            row.ended_at = ended_at
            if is_new:
                self._session.add(row)
            await self._session.flush()
            session_id_map[entry.id] = row.id
            if is_new:
                session_counts.new += 1
            else:
                session_counts.updated += 1
            for member_row in entry.members:
                last_seen = datetime.fromtimestamp(member_row.last_seen, tz=UTC)
                character = await self._get_or_create_character(
                    character_cache,
                    member_row.character,
                    member_row.wow_class.value if member_row.wow_class else None,
                    last_seen,
                )
                first_seen = datetime.fromtimestamp(member_row.first_seen, tz=UTC)
                presence = (
                    await self._session.execute(
                        select(SessionCharacterPresence).where(
                            SessionCharacterPresence.session_id == row.id,
                            SessionCharacterPresence.character_id == character.id,
                        )
                    )
                ).scalar_one_or_none()
                if presence is None:
                    self._session.add(
                        SessionCharacterPresence(
                            session_id=row.id,
                            character_id=character.id,
                            first_seen=first_seen,
                            last_seen=last_seen,
                            standby=member_row.standby,
                        )
                    )
                else:
                    presence.first_seen = min(presence.first_seen, first_seen)
                    presence.last_seen = max(presence.last_seen, last_seen)
                    presence.standby = member_row.standby
            await self._session.flush()

        encounter_counts = ImportCounts()
        encounter_id_map: dict[str, UUID | None] = {}
        for encounter in payload.encounters:
            if encounter.session_id is None:
                encounter_id_map[encounter.id] = None
                continue
            session_internal_id = await self._session_internal_id(session_id_map, encounter.session_id)
            if session_internal_id is None:
                encounter_id_map[encounter.id] = None
                continue
            existing = (
                await self._session.execute(select(Encounter).where(Encounter.external_id == encounter.id))
            ).scalar_one_or_none()
            is_new = existing is None
            row = existing or Encounter(external_id=encounter.id)
            row.session_id = session_internal_id
            row.encounter_id = encounter.encounter_id
            row.name = encounter.name
            row.size = encounter.size
            row.difficulty_id = encounter.difficulty_id
            row.success = encounter.success
            started_at = datetime.fromtimestamp(encounter.started_at, tz=UTC)
            row.started_at = started_at
            row.ended_at = (
                datetime.fromtimestamp(encounter.ended_at, tz=UTC) if encounter.ended_at is not None else started_at
            )
            row.characters = list(encounter.characters)
            row.standby = list(encounter.standby)
            if is_new:
                self._session.add(row)
                encounter_counts.new += 1
                if row.success:
                    await self._add_boss_kill_news(row, session_internal_id)
            else:
                encounter_counts.updated += 1
            await self._session.flush()
            encounter_id_map[encounter.id] = row.id

        loot_counts = LootImportCounts()
        loot_id_map: dict[str, UUID | None] = {}
        for item in payload.loot:
            if item.session_id is None:
                loot_id_map[item.id] = None
                continue
            session_internal_id = await self._session_internal_id(session_id_map, item.session_id)
            if session_internal_id is None:
                loot_id_map[item.id] = None
                continue
            encounter_internal_id = None
            if item.encounter_row_id is not None:
                if item.encounter_row_id in encounter_id_map:
                    encounter_internal_id = encounter_id_map[item.encounter_row_id]
                else:
                    encounter_internal_id = (
                        await self._session.execute(
                            select(Encounter.id).where(Encounter.external_id == item.encounter_row_id)
                        )
                    ).scalar_one_or_none()
            at = datetime.fromtimestamp(item.at, tz=UTC)
            character = await self._get_or_create_character(character_cache, item.character, None, at)
            existing = (
                await self._session.execute(select(LootAward).where(LootAward.external_id == item.id))
            ).scalar_one_or_none()
            if existing is not None and existing.voided_at is not None:
                loot_id_map[item.id] = existing.id
                continue
            is_new = existing is None
            row = existing or LootAward(external_id=item.id)
            row.session_id = session_internal_id
            row.encounter_id = encounter_internal_id
            row.item_id = item.item_id
            row.item_name = item.item_name
            row.quality = item.quality
            row.inv_type = item.inv_type
            row.character_id = character.id
            row.response = item.response.value
            row.gp = item.gp
            row.at = at
            row.officer = item.officer
            if is_new:
                self._session.add(row)
                await self._session.flush()
                if item.voided:
                    row.voided_at = at
                loot_counts.new += 1
                if not item.voided and item.response in (LootResponse.MS, LootResponse.OS):
                    await self._add_news(
                        source_key=f"loot:{row.id}",
                        kind="loot",
                        text=f"{character.name} won {row.item_name}!",
                        at=at,
                        character=character.key,
                        item_id=row.item_id,
                        quality=row.quality,
                    )
            elif item.voided:
                row.voided_at = at
                loot_counts.voided += 1
            else:
                loot_counts.updated += 1
            loot_id_map[item.id] = row.id

        award_counts = AwardImportCounts()
        for award in payload.awards:
            session_internal_id: UUID | None = None
            if award.session_id is not None:
                session_internal_id = await self._session_internal_id(session_id_map, award.session_id)
                if session_internal_id is None:
                    continue
            loot_internal_id = None
            if award.loot_id is not None:
                if award.loot_id in loot_id_map:
                    loot_internal_id = loot_id_map[award.loot_id]
                else:
                    loot_internal_id = (
                        await self._session.execute(select(LootAward.id).where(LootAward.external_id == award.loot_id))
                    ).scalar_one_or_none()
            at = datetime.fromtimestamp(award.at, tz=UTC)
            character = await self._get_or_create_character(character_cache, award.character, None, at)
            existing = (
                await self._session.execute(select(EpgpLedgerEntry).where(EpgpLedgerEntry.external_id == award.id))
            ).scalar_one_or_none()
            if existing is not None and existing.voided_at is not None:
                continue
            is_new = existing is None
            row = existing or EpgpLedgerEntry(external_id=award.id)
            row.kind = award.kind.value
            row.amount = award.amount
            row.reason = award.reason.value
            row.note = award.note
            row.character_id = character.id
            row.member_id = None
            row.loot_id = loot_internal_id
            row.session_id = session_internal_id
            row.at = at
            row.officer = award.officer
            row.source = "addon"
            if is_new:
                self._session.add(row)
                await self._session.flush()
                if award.voided:
                    row.voided_at = at
                award_counts.new += 1
            elif award.voided:
                row.voided_at = at
                award_counts.voided += 1
            else:
                award_counts.updated += 1

        roster_counts = await self._import_roster(payload.roster, character_cache)
        profession_counts = await self._import_professions(payload.professions, character_cache)
        signup_counts = await self._import_signups_v2(payload.signups, character_cache)
        bank_counts = await self._import_bank(payload.bank, character_cache)
        announcement_counts = await self._import_announcements(payload.announcements)
        recruit_counts = await self._import_recruits(payload.recruits, character_cache)
        note_counts = await self._import_member_notes(payload.member_notes, character_cache)

        hand_off_event_id: UUID | None = None
        total_marked = 0
        now = datetime.now(UTC)
        for entry in payload.sessions:
            if session_id_map.get(entry.id) is None or entry.event_id is None:
                continue
            event = await self._session.get(GuildEvent, entry.event_id)
            if event is None:
                continue
            if hand_off_event_id is None:
                hand_off_event_id = entry.event_id
            member_standby: dict[int, bool] = {}
            for member_row in entry.members:
                character = character_cache.get(_character_key(member_row.character))
                if character is None or character.member_id is None:
                    continue
                member_standby[character.member_id] = member_row.standby
            for member_id, standby in member_standby.items():
                signup = (
                    await self._session.execute(
                        select(EventSignup).where(
                            EventSignup.event_id == entry.event_id, EventSignup.member_id == member_id
                        )
                    )
                ).scalar_one_or_none()
                if signup is None:
                    char_name = next(
                        (
                            member_row.character[:24]
                            for member_row in entry.members
                            if character_cache.get(_character_key(member_row.character))
                            and character_cache[_character_key(member_row.character)].member_id == member_id
                        ),
                        None,
                    )
                    self._session.add(
                        EventSignup(
                            event_id=entry.event_id,
                            member_id=member_id,
                            character=char_name,
                            status="signed",
                            attended=True,
                            is_walk_in=True,
                            bench=standby,
                        )
                    )
                    total_marked += 1
                elif signup.attended is None:
                    signup.attended = True
                    total_marked += 1
            if event.attendance_taken_at is None:
                event.attendance_taken_at = now

        self._session.add(
            EpgpImportAudit(
                member_id=actor.id,
                recorder=payload.recorder,
                counts={
                    "sessions": session_counts.model_dump(),
                    "encounters": encounter_counts.model_dump(),
                    "loot": loot_counts.model_dump(),
                    "awards": award_counts.model_dump(),
                    "conflicts": conflicts,
                    "roster": roster_counts.model_dump(),
                    "professions": profession_counts.model_dump(),
                    "signups": signup_counts.model_dump(),
                    "bank": bank_counts.model_dump(),
                    "announcements": announcement_counts.model_dump(),
                    "recruits": recruit_counts.model_dump(),
                    "member_notes": note_counts.model_dump(),
                },
            )
        )
        await self._session.commit()

        unlinked = sorted({row.key for row in character_cache.values() if row.member_id is None})
        return EpgpImportResult(
            recorder=payload.recorder,
            sessions=session_counts,
            encounters=encounter_counts,
            loot=loot_counts,
            awards=award_counts,
            unlinked_characters=unlinked,
            attendance=ImportAttendanceResult(event_id=hand_off_event_id, marked=total_marked),
            conflicts=conflicts,
            roster=roster_counts,
            professions=profession_counts,
            signups=signup_counts,
            bank=bank_counts,
            announcements=announcement_counts,
            recruits=recruit_counts,
            member_notes=note_counts,
        )

    # --- Import v2: guild hub sections ------------------------------------------------------------------------

    async def _add_news(
        self,
        *,
        source_key: str,
        kind: str,
        text: str,
        at: datetime,
        character: str | None = None,
        item_id: int | None = None,
        quality: int | None = None,
    ) -> None:
        """Insert one ``GuildNewsEvent`` if ``source_key`` hasn't been recorded yet (idempotent on re-import)."""
        existing = (
            await self._session.execute(select(GuildNewsEvent.id).where(GuildNewsEvent.source_key == source_key))
        ).scalar_one_or_none()
        if existing is not None:
            return
        self._session.add(
            GuildNewsEvent(
                source_key=source_key,
                kind=kind,
                text=text[:500],
                at=at,
                character=character,
                item_id=item_id,
                quality=quality,
            )
        )

    async def _add_boss_kill_news(self, encounter: Encounter, session_internal_id: UUID) -> None:
        """``first_kill`` news the first time ``encounter.encounter_id`` is ever beaten, else ``boss_kill``."""
        prior_kill = (
            await self._session.execute(
                select(Encounter.id).where(
                    Encounter.encounter_id == encounter.encounter_id,
                    Encounter.success.is_(True),
                    Encounter.id != encounter.id,
                )
            )
        ).scalar_one_or_none()
        raid_session = await self._session.get(RaidSession, session_internal_id)
        instance_name = raid_session.instance_name if raid_session else ""
        kind = "boss_kill" if prior_kill is not None else "first_kill"
        text = f"{encounter.name} defeated" + (f" ({instance_name})" if instance_name else "") + "!"
        await self._add_news(source_key=f"{kind}:{encounter.id}", kind=kind, text=text, at=encounter.started_at)

    async def _import_roster(
        self, roster: ExportRoster | None, character_cache: dict[str, WowCharacter]
    ) -> RosterImportCounts:
        """Upsert the latest roster sweep row per character; level-ups at multiples of ten become news.

        Also sweeps every stored snapshot: one whose ``last_seen_at`` has aged past ``LEFT_GUILD_AFTER_DAYS`` days
        gets ``left_guild_at`` stamped (never deleted), independent of whether this particular sweep saw it.
        """
        counts = RosterImportCounts()
        if roster is None:
            return counts
        taken_at = datetime.fromtimestamp(roster.taken_at, tz=UTC)
        for member_row in roster.members:
            last_seen_at = taken_at - timedelta(hours=member_row.last_online_hours)
            character = await self._get_or_create_character(
                character_cache,
                member_row.character,
                member_row.wow_class.value if member_row.wow_class else None,
                last_seen_at,
            )
            snapshot = (
                await self._session.execute(
                    select(GuildRosterSnapshot).where(GuildRosterSnapshot.character_id == character.id)
                )
            ).scalar_one_or_none()
            previous_level = snapshot.level if snapshot is not None else 0
            is_new = snapshot is None
            row = snapshot or GuildRosterSnapshot(character_id=character.id)
            row.rank = member_row.rank
            row.rank_index = member_row.rank_index
            row.level = member_row.level
            row.zone = member_row.zone
            row.last_seen_at = last_seen_at
            row.left_guild_at = None
            if is_new:
                self._session.add(row)
            counts.updated += 1
            milestone = (member_row.level // LEVEL_MILESTONE_STEP) * LEVEL_MILESTONE_STEP
            previous_milestone = (previous_level // LEVEL_MILESTONE_STEP) * LEVEL_MILESTONE_STEP
            if not is_new and milestone > 0 and milestone > previous_milestone:
                await self._add_news(
                    source_key=f"level:{character.id}:{milestone}",
                    kind="level",
                    text=f"{character.name} reached level {milestone}!",
                    at=last_seen_at,
                    character=character.key,
                )
        await self._session.flush()
        cutoff = taken_at - timedelta(days=LEFT_GUILD_AFTER_DAYS)
        stale = (
            (
                await self._session.execute(
                    select(GuildRosterSnapshot).where(
                        GuildRosterSnapshot.left_guild_at.is_(None), GuildRosterSnapshot.last_seen_at < cutoff
                    )
                )
            )
            .scalars()
            .all()
        )
        for snapshot in stale:
            snapshot.left_guild_at = taken_at
        return counts

    async def _import_professions(
        self, professions: list[ExportProfession], character_cache: dict[str, WowCharacter]
    ) -> ProfessionImportCounts:
        """Upsert per (character, profession); ``recipes`` replaces the stored set for that pair."""
        counts = ProfessionImportCounts()
        for entry in professions:
            scanned_at = datetime.fromtimestamp(entry.scanned_at, tz=UTC)
            character = await self._get_or_create_character(character_cache, entry.character, None, scanned_at)
            row = (
                await self._session.execute(
                    select(CharacterProfession).where(
                        CharacterProfession.character_id == character.id,
                        CharacterProfession.profession == entry.profession,
                    )
                )
            ).scalar_one_or_none()
            is_new = row is None
            row = row or CharacterProfession(character_id=character.id, profession=entry.profession)
            row.skill = entry.skill
            row.max_skill = entry.max_skill
            row.scanned_at = scanned_at
            if is_new:
                self._session.add(row)
            await self._session.flush()
            await self._session.execute(delete(CharacterRecipeLink).where(CharacterRecipeLink.profession_id == row.id))
            for recipe in entry.recipes:
                recipe_row = (
                    await self._session.execute(select(ProfessionRecipe).where(ProfessionRecipe.recipe_id == recipe.id))
                ).scalar_one_or_none()
                if recipe_row is None:
                    recipe_row = ProfessionRecipe(recipe_id=recipe.id, name=recipe.name, item_id=recipe.item_id)
                    self._session.add(recipe_row)
                    await self._session.flush()
                else:
                    recipe_row.name = recipe.name
                    recipe_row.item_id = recipe.item_id
                self._session.add(CharacterRecipeLink(profession_id=row.id, recipe_id=recipe_row.id))
            counts.updated += 1
        await self._session.flush()
        return counts

    async def _import_signups_v2(
        self, signups: list[ExportSignupV2], character_cache: dict[str, WowCharacter]
    ) -> SignupImportCounts:
        """Relay in-game sign-ups into ``EventSignup``: newest ``at`` wins, unlinked characters are skipped."""
        counts = SignupImportCounts()
        for entry in signups:
            key = _character_key(entry.character)
            character = character_cache.get(key)
            if character is None:
                character = (
                    await self._session.execute(select(WowCharacter).where(WowCharacter.key == key))
                ).scalar_one_or_none()
                if character is not None:
                    character_cache[key] = character
            if character is None or character.member_id is None:
                counts.unlinked += 1
                continue
            member = await self._session.get(Member, character.member_id)
            if member is None:
                counts.unlinked += 1
                continue
            event = await self._session.get(GuildEvent, entry.event_id)
            if event is None:
                continue
            at = datetime.fromtimestamp(entry.at, tz=UTC)
            existing = (
                await self._session.execute(
                    select(EventSignup).where(
                        EventSignup.event_id == entry.event_id, EventSignup.member_id == member.id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None and existing.updated_at is not None and existing.updated_at >= at:
                counts.skipped_older += 1
                continue
            fields = {
                "character": entry.character[:24],
                "wow_class": entry.wow_class.value if entry.wow_class else None,
                "role": entry.role.value if entry.role else None,
                "status": entry.status.value,
                "comment": entry.comment,
            }
            if existing is None:
                self._session.add(EventSignup(event_id=entry.event_id, member_id=member.id, **fields))
            else:
                for field, value in fields.items():
                    setattr(existing, field, value)
            counts.applied += 1
        await self._session.flush()
        return counts

    async def _import_bank(
        self, entries: list[ExportBankEntry], character_cache: dict[str, WowCharacter]
    ) -> BankImportCounts:
        """Insert-only guild bank log rows, deduplicated by the addon's deterministic ``id``."""
        counts = BankImportCounts()
        for entry in entries:
            existing = (
                await self._session.execute(
                    select(GuildBankLogEntry.id).where(GuildBankLogEntry.external_id == entry.id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            at = datetime.fromtimestamp(entry.at, tz=UTC)
            character = (
                await self._get_or_create_character(character_cache, entry.character, None, at)
                if entry.character
                else None
            )
            self._session.add(
                GuildBankLogEntry(
                    external_id=entry.id,
                    at=at,
                    character_id=character.id if character else None,
                    kind=entry.kind,
                    item_id=entry.item_id,
                    item_name=entry.item_name,
                    count=entry.count,
                    money=entry.money,
                    tab=entry.tab,
                )
            )
            counts.new += 1
        await self._session.flush()
        return counts

    async def _import_announcements(self, entries: list[ExportAnnouncement]) -> AnnouncementImportCounts:
        """Insert-only game announcements; ``discord: true`` queues one for the bot to post."""
        counts = AnnouncementImportCounts()
        for entry in entries:
            existing = (
                await self._session.execute(
                    select(GuildAnnouncement.id).where(GuildAnnouncement.external_id == entry.id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            at = datetime.fromtimestamp(entry.at, tz=UTC)
            row = GuildAnnouncement(
                external_id=entry.id,
                text=entry.text,
                author=entry.officer,
                at=at,
                source="game",
                discord=entry.discord,
            )
            self._session.add(row)
            await self._session.flush()
            await self._add_news(source_key=f"announcement:{row.id}", kind="announcement", text=entry.text, at=at)
            counts.new += 1
        return counts

    async def _import_recruits(
        self, recruits: list[ExportRecruit], character_cache: dict[str, WowCharacter]
    ) -> RecruitImportCounts:
        """Upsert recruiting candidates by ``id``; votes upsert per (recruit, officer).

        Setting ``status: "trial"`` also sets the linked member's ``raid_status``/``trial_started_at`` if the
        character is linked and the member has no raid status yet.
        """
        counts = RecruitImportCounts()
        for entry in recruits:
            at = datetime.fromtimestamp(entry.at, tz=UTC)
            existing = (
                await self._session.execute(select(GuildRecruit).where(GuildRecruit.external_id == entry.id))
            ).scalar_one_or_none()
            is_new = existing is None
            row = existing or GuildRecruit(external_id=entry.id)
            row.character = entry.character
            row.wow_class = entry.wow_class.value if entry.wow_class else None
            row.status = entry.status
            row.note = entry.note
            row.checklist = entry.checklist.model_dump()
            row.at = at
            if is_new:
                self._session.add(row)
                counts.new += 1
            else:
                counts.updated += 1
            await self._session.flush()
            for vote in entry.votes:
                vote_at = datetime.fromtimestamp(vote.at, tz=UTC)
                vote_row = (
                    await self._session.execute(
                        select(RecruitVote).where(RecruitVote.recruit_id == row.id, RecruitVote.officer == vote.officer)
                    )
                ).scalar_one_or_none()
                if vote_row is None:
                    self._session.add(RecruitVote(recruit_id=row.id, officer=vote.officer, vote=vote.vote, at=vote_at))
                else:
                    vote_row.vote = vote.vote
                    vote_row.at = vote_at
            if entry.status == "trial":
                key = _character_key(entry.character)
                character = (
                    character_cache.get(key)
                    or (
                        await self._session.execute(select(WowCharacter).where(WowCharacter.key == key))
                    ).scalar_one_or_none()
                )
                if character is not None and character.member_id is not None:
                    member = await self._session.get(Member, character.member_id)
                    if member is not None and member.raid_status is None:
                        member.raid_status = "trial"
                        member.trial_started_at = at
        await self._session.flush()
        return counts

    async def _import_member_notes(
        self, notes: list[ExportMemberNote], character_cache: dict[str, WowCharacter]
    ) -> MemberNoteImportCounts:
        """Upsert officer notes by ``id``; voidable, never un-voided."""
        counts = MemberNoteImportCounts()
        for entry in notes:
            existing = (
                await self._session.execute(select(MemberNote).where(MemberNote.external_id == entry.id))
            ).scalar_one_or_none()
            if existing is not None and existing.voided_at is not None:
                continue
            at = datetime.fromtimestamp(entry.at, tz=UTC)
            key = _character_key(entry.character)
            character = (
                character_cache.get(key)
                or (
                    await self._session.execute(select(WowCharacter).where(WowCharacter.key == key))
                ).scalar_one_or_none()
            )
            is_new = existing is None
            row = existing or MemberNote(external_id=entry.id)
            row.character = entry.character
            row.member_id = character.member_id if character else None
            row.note = entry.note
            row.officer = entry.officer
            row.at = at
            if is_new:
                self._session.add(row)
                counts.new += 1
            elif entry.voided:
                row.voided_at = at
                counts.voided += 1
            else:
                counts.updated += 1
        await self._session.flush()
        return counts

    # --- Standings / ledger / loot / progression reads --------------------------------------------------------

    async def get_standings(self, *, now: datetime | None = None) -> EpgpStandings:  # noqa: C901, PLR0912
        """Decayed-on-read EP/GP standings, highest PR first."""
        reference = now or datetime.now(UTC)
        entries = (
            (await self._session.execute(select(EpgpLedgerEntry).where(EpgpLedgerEntry.voided_at.is_(None))))
            .scalars()
            .all()
        )
        characters = {row.id: row for row in (await self._session.execute(select(WowCharacter))).scalars().all()}

        member_buckets: dict[int, dict[str, float]] = {}
        character_buckets: dict[UUID, dict[str, float]] = {}
        unlinked_names: dict[UUID, str] = {}
        for entry in entries:
            decayed = decayed_amount(entry.amount, entry.at, reference)
            bucket: dict[str, float] | None = None
            if entry.member_id is not None:
                bucket = member_buckets.setdefault(entry.member_id, {"ep": 0.0, "gp": 0.0})
            elif entry.character_id is not None:
                character = characters.get(entry.character_id)
                if character is None:
                    continue
                if character.member_id is not None:
                    bucket = member_buckets.setdefault(character.member_id, {"ep": 0.0, "gp": 0.0})
                else:
                    bucket = character_buckets.setdefault(character.id, {"ep": 0.0, "gp": 0.0})
                    unlinked_names[character.id] = character.name
            if bucket is None:
                continue
            bucket["ep" if entry.kind == "ep" else "gp"] += decayed

        member_ids = set(member_buckets)
        roster_members = (
            (await self._session.execute(select(Member).where(Member.raid_status.is_not(None)))).scalars().all()
        )
        member_ids.update(member.id for member in roster_members)
        members: dict[int, Member] = {}
        if member_ids:
            members = {
                member.id: member
                for member in (await self._session.execute(select(Member).where(Member.id.in_(member_ids))))
                .scalars()
                .all()
            }

        chars_by_member: dict[int, list[WowCharacter]] = {}
        for character in characters.values():
            if character.member_id is not None:
                chars_by_member.setdefault(character.member_id, []).append(character)

        rows: list[EpgpStandingsRow] = []
        for member_id in member_ids:
            member = members.get(member_id)
            if member is None:
                continue
            bucket = member_buckets.get(member_id, {"ep": 0.0, "gp": 0.0})
            gp_total = max(MIN_GP, BASE_GP + bucket["gp"])
            ep_total = bucket["ep"]
            member_chars = sorted(chars_by_member.get(member_id, []), key=lambda character: character.key)
            main_char = next((c for c in member_chars if c.is_main), member_chars[0] if member_chars else None)
            trial = bool(
                member.raid_status == "trial"
                and member.trial_started_at is not None
                and (reference - member.trial_started_at) < timedelta(days=TRIAL_DAYS)
            )
            rows.append(
                EpgpStandingsRow(
                    member_id=member_id,
                    name=member.display_name,
                    main=main_char.key if main_char else None,
                    wow_class=WowClass(main_char.wow_class) if main_char and main_char.wow_class else None,
                    characters=[character.key for character in member_chars],
                    ep=round(ep_total, 2),
                    gp=round(gp_total, 2),
                    pr=round(ep_total / gp_total, 4) if gp_total else 0.0,
                    trial=trial,
                )
            )

        for character_id, name in unlinked_names.items():
            character = characters[character_id]
            bucket = character_buckets.get(character_id, {"ep": 0.0, "gp": 0.0})
            gp_total = max(MIN_GP, BASE_GP + bucket["gp"])
            ep_total = bucket["ep"]
            rows.append(
                EpgpStandingsRow(
                    member_id=None,
                    name=name,
                    main=character.key,
                    wow_class=WowClass(character.wow_class) if character.wow_class else None,
                    characters=[character.key],
                    ep=round(ep_total, 2),
                    gp=round(gp_total, 2),
                    pr=round(ep_total / gp_total, 4) if gp_total else 0.0,
                    trial=False,
                )
            )

        rows.sort(key=lambda row: -row.pr)
        rules = EpgpRules(
            ep=EP_VALUES,
            gp=GP_BY_INVTYPE,
            chase_multiplier=CHASE_MULTIPLIER,
            legendary_gp=LEGENDARY_GP,
            os_percent=OS_PERCENT,
            base_gp=BASE_GP,
            min_gp=MIN_GP,
            decay_percent=DECAY_PERCENT,
            trial_days=TRIAL_DAYS,
        )
        return EpgpStandings(generated_at=reference, rules=rules, rows=rows)

    async def _to_ledger_row(self, entry: EpgpLedgerEntry, *, now: datetime) -> EpgpLedgerRow:
        character = await self._session.get(WowCharacter, entry.character_id) if entry.character_id else None
        member_id = entry.member_id if entry.member_id is not None else (character.member_id if character else None)
        member = await self._session.get(Member, member_id) if member_id is not None else None
        item_name = None
        if entry.loot_id is not None:
            loot = await self._session.get(LootAward, entry.loot_id)
            item_name = loot.item_name if loot else None
        return EpgpLedgerRow(
            id=entry.id,
            at=entry.at,
            kind=LedgerKind(entry.kind),
            amount=entry.amount,
            decayed=round(decayed_amount(entry.amount, entry.at, now), 2),
            reason=entry.reason,
            note=entry.note,
            character=character.key if character else None,
            member_id=member_id,
            member_name=member.display_name if member else None,
            officer=entry.officer,
            item_name=item_name,
            voided=entry.voided_at is not None,
        )

    async def get_ledger(
        self, *, member_id: int | None, character: str | None, limit: int, before: datetime | None
    ) -> EpgpLedgerPage:
        """Ledger entries newest first, filtered by member/character.

        ``member_id`` matches entries tied to the member directly or via a linked character.
        """
        now = datetime.now(UTC)
        statement = select(EpgpLedgerEntry)
        if character is not None:
            char_row = (
                await self._session.execute(select(WowCharacter).where(WowCharacter.key == character.lower()))
            ).scalar_one_or_none()
            if char_row is None:
                return EpgpLedgerPage(entries=[])
            statement = statement.where(EpgpLedgerEntry.character_id == char_row.id)
        if member_id is not None:
            character_ids = (
                (await self._session.execute(select(WowCharacter.id).where(WowCharacter.member_id == member_id)))
                .scalars()
                .all()
            )
            conditions = [EpgpLedgerEntry.member_id == member_id]
            if character_ids:
                conditions.append(EpgpLedgerEntry.character_id.in_(character_ids))
            statement = statement.where(or_(*conditions))
        if before is not None:
            statement = statement.where(EpgpLedgerEntry.at < before)
        statement = statement.order_by(EpgpLedgerEntry.at.desc()).limit(limit)
        rows = (await self._session.execute(statement)).scalars().all()
        return EpgpLedgerPage(entries=[await self._to_ledger_row(row, now=now) for row in rows])

    async def get_loot(self, *, limit: int) -> EpgpLootPage:
        """Loot awards newest first."""
        rows = (
            (await self._session.execute(select(LootAward).order_by(LootAward.at.desc()).limit(limit))).scalars().all()
        )
        items: list[EpgpLootRow] = []
        for row in rows:
            character = await self._session.get(WowCharacter, row.character_id) if row.character_id else None
            member = (
                await self._session.get(Member, character.member_id)
                if character and character.member_id is not None
                else None
            )
            raid_session = await self._session.get(RaidSession, row.session_id) if row.session_id else None
            encounter = await self._session.get(Encounter, row.encounter_id) if row.encounter_id else None
            items.append(
                EpgpLootRow(
                    id=row.id,
                    at=row.at,
                    item_id=row.item_id,
                    item_name=row.item_name,
                    quality=row.quality,
                    character=character.key if character else None,
                    member_id=character.member_id if character else None,
                    member_name=member.display_name if member else None,
                    response=LootResponse(row.response),
                    gp=row.gp,
                    instance_name=raid_session.instance_name if raid_session else None,
                    encounter_name=encounter.name if encounter else None,
                    voided=row.voided_at is not None,
                )
            )
        return EpgpLootPage(items=items)

    async def get_progression(self) -> EpgpProgression:
        """Kill/wipe tallies per boss, grouped by instance."""
        rows = (
            await self._session.execute(
                select(Encounter, RaidSession.instance_name, RaidSession.instance_id, RaidSession.size)
                .join(RaidSession, Encounter.session_id == RaidSession.id)
                .order_by(RaidSession.instance_id, Encounter.encounter_id, Encounter.started_at)
            )
        ).all()
        instances: dict[int, dict] = {}
        for encounter, instance_name, instance_id, size in rows:
            instance = instances.setdefault(instance_id, {"name": instance_name, "size": size, "encounters": {}})
            bucket = instance["encounters"].setdefault(
                encounter.encounter_id,
                {
                    "name": encounter.name,
                    "kills": 0,
                    "wipes": 0,
                    "first_kill_at": None,
                    "last_attempt_at": encounter.started_at,
                },
            )
            if encounter.success:
                bucket["kills"] += 1
                if bucket["first_kill_at"] is None or encounter.started_at < bucket["first_kill_at"]:
                    bucket["first_kill_at"] = encounter.started_at
            else:
                bucket["wipes"] += 1
            bucket["last_attempt_at"] = max(bucket["last_attempt_at"], encounter.started_at)
        instance_rows = [
            EpgpProgressionInstance(
                instance_id=instance_id,
                name=data["name"],
                size=data["size"],
                encounters=[
                    EpgpProgressionEncounter(
                        encounter_id=encounter_id,
                        name=bucket["name"],
                        first_kill_at=bucket["first_kill_at"],
                        kills=bucket["kills"],
                        wipes=bucket["wipes"],
                        last_attempt_at=bucket["last_attempt_at"],
                    )
                    for encounter_id, bucket in data["encounters"].items()
                ],
            )
            for instance_id, data in instances.items()
        ]
        return EpgpProgression(instances=instance_rows)

    # --- Game-import string -----------------------------------------------------------------------------------

    async def build_game_import(self, *, now: datetime | None = None) -> EpgpGameImport:
        """Build the ``SQI1:`` string: rules, standings, killed encounters, and upcoming role-kind events."""
        reference = now or datetime.now(UTC)
        standings = await self.get_standings(now=reference)
        killed_rows = (
            (await self._session.execute(select(Encounter.encounter_id).where(Encounter.success.is_(True)).distinct()))
            .scalars()
            .all()
        )
        killed_encounters = sorted(set(killed_rows))

        window_start = reference - _GAME_IMPORT_WINDOW_BEFORE
        window_end = reference + _GAME_IMPORT_WINDOW_AFTER
        events = (
            (
                await self._session.execute(
                    select(GuildEvent)
                    .where(
                        GuildEvent.status == "scheduled",
                        GuildEvent.kind.in_(_ROLE_KINDS),
                        GuildEvent.starts_at >= window_start,
                        GuildEvent.starts_at <= window_end,
                    )
                    .order_by(GuildEvent.starts_at)
                )
            )
            .scalars()
            .all()
        )
        signups_by_event: dict[UUID, list[EventSignup]] = {}
        event_ids = [event.id for event in events]
        if event_ids:
            signup_rows = (
                (await self._session.execute(select(EventSignup).where(EventSignup.event_id.in_(event_ids))))
                .scalars()
                .all()
            )
            for signup in signup_rows:
                signups_by_event.setdefault(signup.event_id, []).append(signup)

        game_events = []
        for event in events:
            signups = []
            for signup in signups_by_event.get(event.id, []):
                if signup.character is None or signup.wow_class is None or signup.role is None:
                    continue
                signups.append(
                    GameImportSignup(
                        character=signup.character,
                        wow_class=WowClass(signup.wow_class),
                        role=SignupRole(signup.role),
                        status=SignupStatus(signup.status),
                        group=signup.chart_group,
                        bench=signup.bench,
                    )
                )
            game_events.append(
                GameImportEvent(
                    id=event.id,
                    title=event.title,
                    kind=EventKind(event.kind),
                    starts_at=int(event.starts_at.timestamp()),
                    size=event.size,
                    signups=signups,
                )
            )

        members, news, sheets, crafters, recipe_names = await self._build_members_news_sheets_crafters(
            reference, standings
        )
        officer = await self._build_officer_game_import(reference)
        payload = GameImportPayload(
            v=2,
            generated_at=int(reference.timestamp()),
            rules=EPGP_RULES,
            standings=[GameImportStandingsRow.model_validate(row.model_dump()) for row in standings.rows],
            killed_encounters=killed_encounters,
            events=game_events,
            members=members,
            news=news,
            sheets=sheets,
            crafters=crafters,
            recipe_names=recipe_names,
            officer=officer,
        )
        encoded = base64.b64encode(json.dumps(payload.model_dump(mode="json", by_alias=True)).encode()).decode()
        return EpgpGameImport(payload=f"{IMPORT_PREFIX}{encoded}", generated_at=reference)

    async def _build_members_news_sheets_crafters(
        self, reference: datetime, standings: EpgpStandings
    ) -> tuple[
        list[GameImportMember],
        list[GameImportNews],
        dict[str, GameImportSheet],
        list[GameImportCrafter],
        dict[str, str],
    ]:
        """The game-import payload's public ``members``/``news`` and on-demand ``sheets``/``crafters`` sections."""
        member_rows = (
            (await self._session.execute(select(Member).where(Member.is_guild_member.is_(True)))).scalars().all()
        )
        member_ids = {member.id for member in member_rows} | {
            row.member_id for row in standings.rows if row.member_id is not None
        }
        all_members = (
            {
                member.id: member
                for member in (await self._session.execute(select(Member).where(Member.id.in_(member_ids))))
                .scalars()
                .all()
            }
            if member_ids
            else {}
        )
        characters = (await self._session.execute(select(WowCharacter))).scalars().all()
        chars_by_member: dict[int, list[WowCharacter]] = {}
        for character in characters:
            if character.member_id is not None:
                chars_by_member.setdefault(character.member_id, []).append(character)
        snapshots = {
            row.character_id: row for row in (await self._session.execute(select(GuildRosterSnapshot))).scalars().all()
        }
        standings_by_member = {row.member_id: row for row in standings.rows if row.member_id is not None}
        badge_rows = (await self._session.execute(select(MemberBadge))).scalars().all()
        badges_by_member: dict[int, list[GameImportBadgeRef]] = {}
        for badge in badge_rows:
            definition = BADGES.get(badge.badge_id)
            if definition is not None:
                badges_by_member.setdefault(badge.member_id, []).append(
                    GameImportBadgeRef(id=definition.id, name=definition.name)
                )
        role_kind_event_count = (
            (
                await self._session.execute(
                    select(GuildEvent.id).where(GuildEvent.kind.in_(_ROLE_KINDS), GuildEvent.status == "completed")
                )
            )
            .scalars()
            .all()
        )
        total_role_events = len(role_kind_event_count)
        attended_rows = (
            await self._session.execute(
                select(EventSignup.member_id, func.count())
                .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
                .where(EventSignup.attended.is_(True), GuildEvent.kind.in_(_ROLE_KINDS))
                .group_by(EventSignup.member_id)
            )
        ).all()
        attended_by_member = {member_id: count for member_id, count in attended_rows}  # noqa: C416 - dict() fails pyrefly here

        members: list[GameImportMember] = []
        sheets: dict[str, GameImportSheet] = {}
        for member_id, member in all_members.items():
            member_chars = sorted(chars_by_member.get(member_id, []), key=lambda character: character.key)
            main_char = next((c for c in member_chars if c.is_main), member_chars[0] if member_chars else None)
            main_snapshot = snapshots.get(main_char.id) if main_char else None
            standings_row = standings_by_member.get(member_id)
            events_attended = attended_by_member.get(member_id, 0)
            members.append(
                GameImportMember(
                    member_id=member_id,
                    name=member.display_name,
                    main=main_char.key if main_char else None,
                    wow_class=WowClass(main_char.wow_class) if main_char and main_char.wow_class else None,
                    rank=main_snapshot.rank if main_snapshot else None,
                    raid_status=member.raid_status,
                    guild_ep=round(standings_row.ep) if standings_row else 0,
                    attendance_rate=round(events_attended / total_role_events, 4) if total_role_events else 0.0,
                    events_attended=events_attended,
                    badges=badges_by_member.get(member_id, []),
                    characters=[
                        GameImportCharacter(
                            name=character.key,
                            wow_class=WowClass(character.wow_class) if character.wow_class else None,
                            level=snapshots[character.id].level if character.id in snapshots else 0,
                            is_main=character.is_main,
                        )
                        for character in member_chars
                    ],
                )
            )
            ledger_page = await self.get_ledger(member_id=member_id, character=None, limit=15, before=None)
            char_ids = [character.id for character in member_chars]
            loot_rows = (
                (
                    await self._session.execute(
                        select(LootAward)
                        .where(LootAward.character_id.in_(char_ids), LootAward.voided_at.is_(None))
                        .order_by(LootAward.at.desc())
                        .limit(10)
                    )
                )
                .scalars()
                .all()
                if char_ids
                else []
            )
            sheets[str(member_id)] = GameImportSheet(
                ledger=[
                    GameImportLedgerEntry(
                        at=int(entry.at.timestamp()),
                        kind=entry.kind.value,
                        amount=entry.amount,
                        decayed=entry.decayed,
                        reason=entry.reason,
                        note=entry.note,
                    )
                    for entry in ledger_page.entries
                ],
                loot=[
                    GameImportLootEntry(
                        at=int(row.at.timestamp()),
                        item_id=row.item_id,
                        item_name=row.item_name,
                        quality=row.quality,
                        gp=row.gp,
                        response=row.response,
                    )
                    for row in loot_rows
                ],
            )

        news_cutoff = reference - timedelta(days=14)
        news_rows = (
            (
                await self._session.execute(
                    select(GuildNewsEvent)
                    .where(GuildNewsEvent.at >= news_cutoff)
                    .order_by(GuildNewsEvent.at.desc())
                    .limit(60)
                )
            )
            .scalars()
            .all()
        )
        news = [
            GameImportNews(
                id=str(row.id),
                at=int(row.at.timestamp()),
                kind=row.kind,
                text=row.text,
                character=row.character,
                item_id=row.item_id,
                quality=row.quality,
            )
            for row in news_rows
        ]

        profession_rows = (await self._session.execute(select(CharacterProfession))).scalars().all()
        link_rows = (
            await self._session.execute(
                select(CharacterRecipeLink.profession_id, ProfessionRecipe.recipe_id, ProfessionRecipe.name).join(
                    ProfessionRecipe, CharacterRecipeLink.recipe_id == ProfessionRecipe.id
                )
            )
        ).all()
        recipe_ids_by_profession: dict[UUID, list[int]] = {}
        recipe_names: dict[str, str] = {}
        for profession_id, recipe_id, name in link_rows:
            recipe_ids_by_profession.setdefault(profession_id, []).append(recipe_id)
            recipe_names[str(recipe_id)] = name
        characters_by_id = {character.id: character for character in characters}
        crafters = [
            GameImportCrafter(
                character=characters_by_id[profession.character_id].key,
                member_id=characters_by_id[profession.character_id].member_id,
                profession=profession.profession,
                skill=profession.skill,
                recipes=recipe_ids_by_profession.get(profession.id, []),
            )
            for profession in profession_rows
            if profession.character_id in characters_by_id
        ]
        return members, news, sheets, crafters, recipe_names

    async def _build_officer_game_import(self, reference: datetime) -> GameImportOfficerPart:
        """The officer-only ``recruits``/``member_notes``/``inactive`` section of the game-import payload.

        ``inactive`` flags a member seen in neither a roster sweep nor a raid session within
        ``INACTIVE_AFTER_DAYS`` days (never seen in either counts as inactive too).
        """
        recruit_rows = (await self._session.execute(select(GuildRecruit))).scalars().all()
        vote_rows = (await self._session.execute(select(RecruitVote))).scalars().all()
        votes_by_recruit: dict[UUID, list[ExportRecruitVote]] = {}
        for vote in vote_rows:
            votes_by_recruit.setdefault(vote.recruit_id, []).append(
                ExportRecruitVote(officer=vote.officer, vote=vote.vote, at=int(vote.at.timestamp()))
            )
        character_by_key = {
            character.key: character
            for character in (await self._session.execute(select(WowCharacter))).scalars().all()
        }

        def _recruit_member_id(character_key: str) -> int | None:
            character = character_by_key.get(character_key)
            return character.member_id if character is not None else None

        officer_recruits = [
            GameImportOfficerRecruit(
                id=recruit.external_id or str(recruit.id),
                character=recruit.character,
                wow_class=WowClass(recruit.wow_class) if recruit.wow_class else None,
                status=recruit.status,
                note=recruit.note,
                checklist=RecruitChecklist.model_validate(recruit.checklist),
                votes=votes_by_recruit.get(recruit.id, []),
                at=int(recruit.at.timestamp()),
                member_id=_recruit_member_id(_character_key(recruit.character)),
            )
            for recruit in recruit_rows
        ]
        note_rows = (await self._session.execute(select(MemberNote))).scalars().all()
        officer_notes = [
            GameImportOfficerNote(
                id=note.external_id,
                character=note.character,
                note=note.note,
                officer=note.officer,
                at=int(note.at.timestamp()),
                voided=note.voided_at is not None,
            )
            for note in note_rows
        ]
        cutoff = reference - timedelta(days=INACTIVE_AFTER_DAYS)
        snapshots = (await self._session.execute(select(GuildRosterSnapshot))).scalars().all()
        last_seen_by_character = {row.character_id: row.last_seen_at for row in snapshots}
        presences = (await self._session.execute(select(SessionCharacterPresence))).scalars().all()
        last_raid_by_character: dict[UUID, datetime] = {}
        for presence in presences:
            current = last_raid_by_character.get(presence.character_id)
            if current is None or presence.last_seen > current:
                last_raid_by_character[presence.character_id] = presence.last_seen
        members = (await self._session.execute(select(Member).where(Member.is_guild_member.is_(True)))).scalars().all()
        characters = (await self._session.execute(select(WowCharacter))).scalars().all()
        chars_by_member: dict[int, list[WowCharacter]] = {}
        for character in characters:
            if character.member_id is not None:
                chars_by_member.setdefault(character.member_id, []).append(character)
        inactive = []
        for member in members:
            member_chars = chars_by_member.get(member.id, [])
            last_seen = max(
                (last_seen_by_character[c.id] for c in member_chars if c.id in last_seen_by_character),
                default=None,
            )
            last_raid = max(
                (last_raid_by_character[c.id] for c in member_chars if c.id in last_raid_by_character),
                default=None,
            )
            if (last_seen is None or last_seen < cutoff) and (last_raid is None or last_raid < cutoff):
                inactive.append(
                    GameImportInactiveMember(
                        member_id=member.id,
                        name=member.display_name,
                        last_seen_at=int(last_seen.timestamp()) if last_seen else None,
                        last_raid_at=int(last_raid.timestamp()) if last_raid else None,
                    )
                )
        return GameImportOfficerPart(recruits=officer_recruits, member_notes=officer_notes, inactive=inactive)

    # --- Officer: adjustments ----------------------------------------------------------------------------------

    async def create_adjustment(self, data: EpgpAdjustmentCreate, actor: Member) -> EpgpLedgerRow:
        """A site-made EP/GP ledger entry, reason ``adjust``, attributed to ``actor``'s display name."""
        member = await self._session.get(Member, data.member_id)
        if member is None:
            msg = f"No member {data.member_id}"
            raise NotFoundException(msg)
        now = datetime.now(UTC)
        entry = EpgpLedgerEntry(
            kind=data.kind.value,
            amount=data.amount,
            reason="adjust",
            note=data.reason,
            member_id=data.member_id,
            at=now,
            officer=actor.display_name,
            source="site",
        )
        self._session.add(entry)
        await self._session.commit()
        return await self._to_ledger_row(entry, now=now)

    # --- Officer: characters admin ------------------------------------------------------------------------------

    async def _to_character_schema(self, character: WowCharacter) -> EpgpCharacter:
        member = await self._session.get(Member, character.member_id) if character.member_id is not None else None
        return EpgpCharacter(
            id=character.id,
            name=character.name,
            realm=character.realm,
            wow_class=WowClass(character.wow_class) if character.wow_class else None,
            member_id=character.member_id,
            member_name=member.display_name if member else None,
            is_main=character.is_main,
            source=CharacterSource(character.source),
            last_seen_at=character.last_seen_at,
        )

    async def list_characters(self) -> EpgpCharacterList:
        """Every known character, officer admin view."""
        rows = (await self._session.execute(select(WowCharacter).order_by(WowCharacter.key))).scalars().all()
        return EpgpCharacterList(characters=[await self._to_character_schema(row) for row in rows])

    async def update_character(self, character_id: UUID, data: EpgpCharacterUpdate) -> EpgpCharacter:
        """Relink a character, or mark it as its member's main."""
        character = await self._session.get(WowCharacter, character_id)
        if character is None:
            msg = f"No character {character_id}"
            raise NotFoundException(msg)
        character.member_id = data.member_id
        character.is_main = data.is_main
        if data.member_id is not None:
            character.source = "officer"
            if data.is_main:
                others = (
                    (
                        await self._session.execute(
                            select(WowCharacter).where(
                                WowCharacter.member_id == data.member_id, WowCharacter.id != character_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for other in others:
                    other.is_main = False
        await self._session.commit()
        return await self._to_character_schema(character)

    # --- Officer: roster -----------------------------------------------------------------------------------------

    async def list_roster(self) -> EpgpRoster:
        """Guild members' EPGP roster status."""
        rows = (await self._session.execute(select(Member).where(Member.is_guild_member.is_(True)))).scalars().all()
        ordered = sorted(rows, key=lambda member: member.display_name.casefold())
        return EpgpRoster(
            members=[
                EpgpRosterRow(
                    member_id=member.id,
                    name=member.display_name,
                    raid_status=RaidStatus(member.raid_status) if member.raid_status else None,
                    trial_started_at=member.trial_started_at,
                )
                for member in ordered
            ]
        )

    async def update_roster(self, member_id: int, data: EpgpRosterUpdate) -> EpgpRosterRow:
        """Set a member's raid status; setting ``"trial"`` stamps ``trial_started_at`` now."""
        member = await self._session.get(Member, member_id)
        if member is None:
            msg = f"No member {member_id}"
            raise NotFoundException(msg)
        member.raid_status = data.raid_status.value if data.raid_status is not None else None
        if data.raid_status == RaidStatus.TRIAL:
            member.trial_started_at = datetime.now(UTC)
        await self._session.commit()
        return EpgpRosterRow(
            member_id=member.id,
            name=member.display_name,
            raid_status=data.raid_status,
            trial_started_at=member.trial_started_at,
        )

    # --- Officer: sync tokens --------------------------------------------------------------------------------

    async def list_sync_tokens(self, officer: Member) -> EpgpSyncTokenList:
        """``officer``'s own non-revoked sync tokens."""
        rows = (
            (
                await self._session.execute(
                    select(EpgpSyncToken)
                    .where(EpgpSyncToken.member_id == officer.id, EpgpSyncToken.revoked_at.is_(None))
                    .order_by(EpgpSyncToken.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return EpgpSyncTokenList(
            tokens=[
                EpgpSyncTokenSummary(id=row.id, name=row.name, created_at=row.created_at, last_used_at=row.last_used_at)
                for row in rows
            ]
        )

    async def create_sync_token(self, officer: Member, data: EpgpSyncTokenCreate) -> EpgpSyncTokenCreated:
        """Create a sync token for ``officer``; the plaintext is returned once and never stored."""
        token = _TOKEN_PREFIX + "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_RANDOM_LENGTH))
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        row = EpgpSyncToken(member_id=officer.id, name=data.name, token_hash=token_hash)
        self._session.add(row)
        await self._session.commit()
        return EpgpSyncTokenCreated(id=row.id, name=row.name, token=token)

    async def revoke_sync_token(self, officer: Member, token_id: UUID) -> None:
        """Revoke one of ``officer``'s own sync tokens. 404 unknown/not own/already revoked."""
        row = await self._session.get(EpgpSyncToken, token_id)
        if row is None or row.member_id != officer.id or row.revoked_at is not None:
            msg = f"No sync token {token_id}"
            raise NotFoundException(msg)
        row.revoked_at = datetime.now(UTC)
        await self._session.commit()

    # --- Member: self-service characters ------------------------------------------------------------------------

    async def list_my_characters(self, member: Member) -> EpgpCharacterList:
        """The signed-in member's own characters."""
        rows = (
            (
                await self._session.execute(
                    select(WowCharacter).where(WowCharacter.member_id == member.id).order_by(WowCharacter.key)
                )
            )
            .scalars()
            .all()
        )
        return EpgpCharacterList(characters=[await self._to_character_schema(row) for row in rows])

    async def claim_character(self, member: Member, data: MyCharacterCreate) -> EpgpCharacter:
        """Self-claim a character by name-realm. 409 if another member already claimed it."""
        realm = data.realm or DEFAULT_REALM
        key = f"{data.name.lower()}-{realm.lower()}"
        existing = (
            await self._session.execute(select(WowCharacter).where(WowCharacter.key == key))
        ).scalar_one_or_none()
        if existing is not None and existing.member_id is not None and existing.member_id != member.id:
            msg = "Another member already claimed that character"
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg)
        if existing is None:
            character = WowCharacter(
                name=data.name,
                realm=realm,
                key=key,
                member_id=member.id,
                source="claim",
                wow_class=data.wow_class.value if data.wow_class else None,
            )
            self._session.add(character)
        else:
            character = existing
            character.member_id = member.id
            character.source = "claim"
            if data.wow_class is not None:
                character.wow_class = data.wow_class.value
        await self._session.commit()
        return await self._to_character_schema(character)

    async def delete_my_character(self, member: Member, character_id: UUID) -> None:
        """Remove one of ``member``'s own characters. 404 unknown/not own character."""
        character = await self._session.get(WowCharacter, character_id)
        if character is None or character.member_id != member.id:
            msg = f"No character {character_id}"
            raise NotFoundException(msg)
        await self._session.delete(character)
        await self._session.commit()
