"""EPGP: decay math, standings, the SQX1: import (idempotency, voiding, conflicts, auto-link, attendance hand-off),
bounds rejection, sync-token auth, member character self-claim, and the SQI1: game-import string."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from sidequest_api.domain.epgp.services import decayed_amount, resets_since
from sidequest_common.models import (
    EpgpDeviceAuthorization,
    EpgpImportAudit,
    EpgpLedgerEntry,
    EpgpSyncToken,
    EventSignup,
    GuildEvent,
    LootAward,
    Member,
    RaidSession,
    WowCharacter,
)
from tests.conftest import GUILD_ID
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PAST = datetime.now(UTC) - timedelta(hours=2)
RECORDER = "Officername-Whitemane"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _export_string(payload: dict) -> str:
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"SQX1:{encoded}"


def _base_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "v": 1,
        "addon_version": "1.0.0",
        "exported_at": 1793500000,
        "guild": "SideQuest",
        "realm": "Whitemane",
        "recorder": RECORDER,
        "sessions": [],
        "encounters": [],
        "loot": [],
        "awards": [],
    }
    payload.update(overrides)
    return payload


def _session_row(session_id: str = "S1", **overrides: object) -> dict:
    row: dict[str, object] = {
        "id": session_id,
        "event_id": None,
        "instance_name": "Hyjal Summit",
        "instance_id": 534,
        "difficulty_id": 3,
        "size": 20,
        "started_at": 1793490000,
        "ended_at": 1793500000,
        "members": [],
    }
    row.update(overrides)
    return row


def _member_row(character: str, wow_class: str, *, standby: bool = False) -> dict:
    return {
        "character": character,
        "class": wow_class,
        "first_seen": 1793490000,
        "last_seen": 1793500000,
        "standby": standby,
    }


def _award_row(award_id: str = "A1", **overrides: object) -> dict:
    row: dict[str, object] = {
        "id": award_id,
        "session_id": "S1",
        "kind": "ep",
        "character": "Tank1-Whitemane",
        "amount": 10,
        "reason": "boss_kill",
        "note": None,
        "loot_id": None,
        "at": 1793491300,
        "officer": RECORDER,
        "voided": False,
    }
    row.update(overrides)
    return row


def _loot_row(loot_id: str = "L1", **overrides: object) -> dict:
    row: dict[str, object] = {
        "id": loot_id,
        "session_id": "S1",
        "encounter_row_id": None,
        "item_id": 19019,
        "item_name": "Thunderfury, Blessed Blade of the Windseeker",
        "quality": 4,
        "inv_type": "INVTYPE_WEAPONMAINHAND",
        "character": "Tank1-Whitemane",
        "response": "council",
        "gp": 300,
        "at": 1793491300,
        "officer": RECORDER,
        "voided": False,
        "council_reason": "Best in slot for progression.",
        "council_kind": "legendary",
    }
    row.update(overrides)
    return row


async def _login_officer(client: AsyncTestClient, discord_state: dict, *, discord_id: int = 100) -> None:
    response = await login_as(client, discord_state, discord_id=discord_id, roles=[OFFICER_ROLE_ID])
    assert response.status_code == 302, response.text


async def _create_member_sync_token(
    client: AsyncTestClient, discord_state: dict, *, discord_id: int, name: str = "Companion"
) -> str:
    """Any guild member's device-sign-in flow (no officer role needed): create, self-approve, and poll for the
    token, same as SideQuest Companion does."""
    created = await client.post("/api/epgp/device-authorizations", json={"device_name": name})
    assert created.status_code == 201, created.text
    await login_as(client, discord_state, discord_id=discord_id, roles=[])
    approve = await client.post(f"/api/epgp/device-authorizations/{created.json()['user_code']}/approve")
    assert approve.status_code == 204, approve.text
    poll = await client.post(
        "/api/epgp/device-authorizations/token", json={"device_code": created.json()["device_code"]}
    )
    assert poll.status_code == 200, poll.text
    assert poll.json()["status"] == "approved", poll.text
    return poll.json()["token"]


# --- decay math -----------------------------------------------------------------------------------------------


def test_resets_since_counts_tuesday_fifteen_utc_boundaries() -> None:
    before_reset = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)  # Tuesday, before that week's reset
    after_one_reset = datetime(2026, 11, 3, 16, 0, tzinfo=UTC)  # same Tuesday, after reset
    after_two_resets = datetime(2026, 11, 10, 16, 0, tzinfo=UTC)  # the following Tuesday, after reset
    assert resets_since(before_reset, before_reset) == 0
    assert resets_since(before_reset, after_one_reset) == 1
    assert resets_since(before_reset, after_two_resets) == 2
    assert resets_since(after_one_reset, after_one_reset) == 0


def test_decayed_amount_applies_fifteen_percent_per_reset() -> None:
    at = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
    now_two_resets = datetime(2026, 11, 10, 16, 0, tzinfo=UTC)
    assert decayed_amount(100, at, at) == 100
    assert round(decayed_amount(100, at, now_two_resets), 4) == round(100 * 0.85 * 0.85, 4)


# --- standings: decay on read, GP floor, PR ordering -----------------------------------------------------------


async def test_standings_gp_never_below_floor(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=6001, username="lowgp", is_guild_member=True, raid_status="raider")
        session.add(member)
        await session.commit()

    response = await client.get("/api/epgp/standings")
    assert response.status_code == 200
    rows = {row["member_id"]: row for row in response.json()["rows"]}
    row = next(r for r in rows.values() if r["name"] == "lowgp")
    assert row["gp"] == 100.0  # base GP, no GP-kind ledger entries at all


async def test_standings_lists_rostered_member_with_no_raids_at_zero_ep_and_pr(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """The "everyone listed" rule: a member on the EPGP roster (``raid_status`` set) with no ledger entries at all
    still shows up, at 0 EP, the GP floor, and PR 0 — the standings table is never empty while the guild has a
    rostered member, even before their first raid."""
    async with db_sessionmaker() as session:
        member = Member(discord_id=6010, username="norads", is_guild_member=True, raid_status="trial")
        session.add(member)
        await session.commit()

    response = await client.get("/api/epgp/standings")
    assert response.status_code == 200
    row = next(r for r in response.json()["rows"] if r["name"] == "norads")
    assert row["ep"] == 0.0
    assert row["gp"] == 100.0
    assert row["pr"] == 0.0


async def test_standings_list_every_confirmed_guild_member_with_their_main_by_game_name(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A member confirmed on the guild roster is on the Ledger before any raid or raid-roster status; one who has
    left the guild isn't. The main shows as the game writes it, ``First Surname``."""
    confirmed_at = datetime(2026, 11, 1, tzinfo=UTC)
    async with db_sessionmaker() as session:
        member = Member(discord_id=6020, username="confirmed", is_guild_member=True, roster_confirmed_at=confirmed_at)
        departed = Member(discord_id=6021, username="departed", is_guild_member=False, roster_confirmed_at=confirmed_at)
        session.add_all([member, departed])
        await session.flush()
        session.add(
            WowCharacter(
                name="Legs",
                realm="forever",
                key="legs-behindhead",
                surname="Behindhead",
                member_id=member.id,
                is_main=True,
            )
        )
        await session.commit()

    rows = (await client.get("/api/epgp/standings")).json()["rows"]
    row = next(r for r in rows if r["name"] == "confirmed")
    assert (row["ep"], row["gp"], row["pr"]) == (0.0, 100.0, 0.0)
    assert row["main"] == "legs-behindhead"
    assert row["main_name"] == "Legs Behindhead"
    assert all(r["name"] != "departed" for r in rows)


async def test_standings_rules_include_weekly_reset_fields(client: AsyncTestClient) -> None:
    response = await client.get("/api/epgp/standings")
    rules = response.json()["rules"]
    assert rules["weekly_reset_weekday"] == 1  # Tuesday, datetime.weekday() convention
    assert rules["weekly_reset_hour_utc"] == 15


async def test_standings_orders_by_pr_descending(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        high = Member(discord_id=6002, username="highpr", is_guild_member=True)
        low = Member(discord_id=6003, username="lowpr", is_guild_member=True)
        session.add_all([high, low])
        await session.flush()
        now = datetime.now(UTC)
        session.add_all(
            [
                EpgpLedgerEntry(
                    kind="ep", amount=500, reason="adjust", member_id=high.id, at=now, officer="Test", source="site"
                ),
                EpgpLedgerEntry(
                    kind="ep", amount=10, reason="adjust", member_id=low.id, at=now, officer="Test", source="site"
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/epgp/standings")
    rows = response.json()["rows"]
    names = [row["name"] for row in rows if row["name"] in ("highpr", "lowpr")]
    assert names == ["highpr", "lowpr"]


# --- import idempotency, voiding, conflicts ----------------------------------------------------------------


async def test_import_same_payload_twice_creates_no_new_rows(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state)
    payload = _base_payload(
        sessions=[_session_row(members=[_member_row("Tank1-Whitemane", "warrior")])],
        awards=[_award_row()],
    )
    body = {"payload": _export_string(payload)}

    first = await member_client.post("/api/epgp/imports", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["sessions"]["new"] == 1
    assert first.json()["awards"]["new"] == 1

    second = await member_client.post("/api/epgp/imports", json=body)
    assert second.status_code == 200
    assert second.json()["sessions"]["new"] == 0
    assert second.json()["sessions"]["updated"] == 1
    assert second.json()["awards"]["new"] == 0

    async with db_sessionmaker() as session:
        session_count = (await session.execute(select(func.count()).select_from(RaidSession))).scalar_one()
        award_count = (await session.execute(select(func.count()).select_from(EpgpLedgerEntry))).scalar_one()
        assert session_count == 1
        assert award_count == 1


async def test_import_canonicalizes_legacy_forever_space_separated_character_names(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Addon versions before the Forever identity fix (v0.8.0 and earlier) exported the raw "First Surname"
    shape with a stray "-<realm>" tail (GetNormalizedRealmName() mistakenly appended to an already-complete
    name); a fixed addon sends the canonical "First-Surname" link form instead. Both must resolve to the same
    WowCharacter row, not create a duplicate."""
    await _login_officer(member_client, discord_state)
    legacy_payload = _base_payload(
        awards=[_award_row(award_id="A1", character="Legs Behindhead-ShatteredHalls", session_id=None)]
    )
    first = await member_client.post("/api/epgp/imports", json={"payload": _export_string(legacy_payload)})
    assert first.status_code == 200, first.text

    fixed_payload = _base_payload(awards=[_award_row(award_id="A2", character="Legs-Behindhead", session_id=None)])
    second = await member_client.post("/api/epgp/imports", json={"payload": _export_string(fixed_payload)})
    assert second.status_code == 200, second.text

    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(WowCharacter).where(WowCharacter.key == "legs-behindhead"))).scalars().all()
        )
        assert len(rows) == 1, "the legacy and fixed exports land on the same character row"
        assert rows[0].name == "Legs"
        assert rows[0].realm == "Behindhead"


async def test_voiding_sets_voided_at_and_excludes_from_standings_and_cannot_unvoid(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state)
    payload = _base_payload(
        sessions=[_session_row(members=[_member_row("Voidy-Whitemane", "mage")])],
        awards=[_award_row(character="Voidy-Whitemane", kind="gp", amount=200, reason="loot")],
    )
    first = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert first.status_code == 200

    voided_payload = _base_payload(
        sessions=payload["sessions"],
        awards=[_award_row(character="Voidy-Whitemane", kind="gp", amount=200, reason="loot", voided=True)],
    )
    second = await member_client.post("/api/epgp/imports", json={"payload": _export_string(voided_payload)})
    assert second.status_code == 200
    assert second.json()["awards"]["voided"] == 1

    ledger_stmt = select(EpgpLedgerEntry).where(EpgpLedgerEntry.external_id == "A1")
    async with db_sessionmaker() as session:
        entry = (await session.execute(ledger_stmt)).scalar_one()
        assert entry.voided_at is not None

    # Cannot be un-voided by re-importing the same id as not-voided.
    third = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert third.status_code == 200
    assert third.json()["awards"]["updated"] == 0
    assert third.json()["awards"]["voided"] == 0
    async with db_sessionmaker() as session:
        entry = (await session.execute(ledger_stmt)).scalar_one()
        assert entry.voided_at is not None


# --- per-person ledger history: filtering, decay, voided entries, loot response ------------------------------


async def test_ledger_filters_by_member_id_and_decays_on_read(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=6020, username="historied", is_guild_member=True, raid_status="raider")
        other = Member(discord_id=6021, username="someoneelse", is_guild_member=True, raid_status="raider")
        session.add_all([member, other])
        await session.flush()
        old_award_at = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
        session.add_all(
            [
                EpgpLedgerEntry(
                    kind="ep",
                    amount=100,
                    reason="boss_kill",
                    member_id=member.id,
                    at=old_award_at,
                    officer="Test",
                    source="site",
                ),
                EpgpLedgerEntry(
                    kind="ep",
                    amount=10,
                    reason="boss_kill",
                    member_id=other.id,
                    at=old_award_at,
                    officer="Test",
                    source="site",
                ),
            ]
        )
        await session.commit()

    response = await client.get(f"/api/epgp/ledger?member_id={member.id}")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["member_id"] == member.id
    assert entries[0]["amount"] == 100
    # Decay is read-time: more than zero resets have landed since `two_resets_ago`, so `decayed` is less than 100.
    assert entries[0]["decayed"] < 100


async def test_ledger_includes_voided_entries_flagged_rather_than_excluded(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=6022, username="voidedhistory", is_guild_member=True, raid_status="raider")
        session.add(member)
        await session.flush()
        session.add(
            EpgpLedgerEntry(
                kind="ep",
                amount=10,
                reason="boss_kill",
                member_id=member.id,
                at=PAST,
                officer="Test",
                source="site",
                voided_at=PAST,
            )
        )
        await session.commit()

    response = await client.get(f"/api/epgp/ledger?member_id={member.id}")
    entries = response.json()["entries"]
    assert len(entries) == 1  # voiding marks, never removes
    assert entries[0]["voided"] is True


async def test_ledger_gp_charge_reports_the_loot_response(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=6023, username="lootwinner", is_guild_member=True, raid_status="raider")
        session.add(member)
        await session.flush()
        loot = LootAward(
            external_id="loot-history-1",
            item_id=19019,
            item_name="Thunderfury, Blessed Blade of the Windseeker",
            quality=4,
            inv_type="INVTYPE_WEAPONMAINHAND",
            response="os",
            gp=30,
            at=PAST,
            officer=RECORDER,
        )
        session.add(loot)
        await session.flush()
        session.add(
            EpgpLedgerEntry(
                kind="gp",
                amount=30,
                reason="loot",
                member_id=member.id,
                loot_id=loot.id,
                at=PAST,
                officer=RECORDER,
                source="addon",
            )
        )
        await session.commit()

    response = await client.get(f"/api/epgp/ledger?member_id={member.id}")
    entries = response.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["item_name"] == "Thunderfury, Blessed Blade of the Windseeker"
    assert entries[0]["response"] == "os"


async def test_conflicting_recorder_session_is_skipped(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state)
    first_payload = _base_payload(
        recorder="RecorderOne-Whitemane",
        sessions=[_session_row(session_id="S1", instance_id=999)],
    )
    first = await member_client.post("/api/epgp/imports", json={"payload": _export_string(first_payload)})
    assert first.status_code == 200
    assert first.json()["sessions"]["new"] == 1

    conflicting_payload = _base_payload(
        recorder="RecorderTwo-Whitemane",
        sessions=[_session_row(session_id="S2", instance_id=999, started_at=1793491000, ended_at=1793499000)],
    )
    second = await member_client.post("/api/epgp/imports", json={"payload": _export_string(conflicting_payload)})
    assert second.status_code == 200
    assert second.json()["sessions"]["new"] == 0
    assert "S2" in second.json()["conflicts"]


# --- auto-link ------------------------------------------------------------------------------------------------


async def test_auto_link_unique_signup_name_links_character(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        event = GuildEvent(kind="raid", title="Raid", location="", starts_at=PAST, status="scheduled")
        session.add(event)
        await session.flush()
        member = Member(discord_id=6101, username="uniquename", is_guild_member=True)
        session.add(member)
        await session.flush()
        session.add(EventSignup(event_id=event.id, member_id=member.id, character="Uniquo", status="signed"))
        await session.commit()
        member_id = member.id

    await _login_officer(member_client, discord_state)
    payload = _base_payload(sessions=[_session_row(members=[_member_row("Uniquo-Whitemane", "rogue")])])
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200

    async with db_sessionmaker() as session:
        stmt = select(WowCharacter).where(WowCharacter.key == "uniquo-whitemane")
        character = (await session.execute(stmt)).scalar_one()
        assert character.member_id == member_id
        assert character.source == "signup"


async def test_auto_link_ambiguous_signup_name_stays_unlinked(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        event_a = GuildEvent(kind="raid", title="Raid A", location="", starts_at=PAST, status="scheduled")
        event_b = GuildEvent(kind="raid", title="Raid B", location="", starts_at=PAST, status="scheduled")
        session.add_all([event_a, event_b])
        await session.flush()
        member_a = Member(discord_id=6102, username="ambigA", is_guild_member=True)
        member_b = Member(discord_id=6103, username="ambigB", is_guild_member=True)
        session.add_all([member_a, member_b])
        await session.flush()
        session.add_all(
            [
                EventSignup(event_id=event_a.id, member_id=member_a.id, character="Dupe", status="signed"),
                EventSignup(event_id=event_b.id, member_id=member_b.id, character="Dupe", status="signed"),
            ]
        )
        await session.commit()

    await _login_officer(member_client, discord_state)
    payload = _base_payload(sessions=[_session_row(members=[_member_row("Dupe-Whitemane", "hunter")])])
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200
    assert "dupe-whitemane" in response.json()["unlinked_characters"]

    async with db_sessionmaker() as session:
        stmt = select(WowCharacter).where(WowCharacter.key == "dupe-whitemane")
        character = (await session.execute(stmt)).scalar_one()
        assert character.member_id is None


# --- attendance hand-off ---------------------------------------------------------------------------------------


async def test_attendance_hand_off_flips_none_to_true_creates_walk_in_and_leaves_false_untouched(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        event = GuildEvent(kind="raid", title="Hand-off Raid", location="", starts_at=PAST, status="scheduled")
        session.add(event)
        await session.flush()
        event_id = event.id
        member_a = Member(discord_id=6201, username="flipme", is_guild_member=True)
        member_c = Member(discord_id=6202, username="stayfalse", is_guild_member=True)
        session.add_all([member_a, member_c])
        await session.flush()
        session.add_all(
            [
                EventSignup(
                    event_id=event.id, member_id=member_a.id, character="Flipme", status="signed", attended=None
                ),
                EventSignup(
                    event_id=event.id, member_id=member_c.id, character="Ghost1", status="signed", attended=False
                ),
            ]
        )
        await session.commit()
        member_a_id, member_c_id = member_a.id, member_c.id

    # Member B self-claims a character with no sign-up on this event, to become a walk-in.
    await login_as(member_client, discord_state, discord_id=6203, roles=[])
    claim = await member_client.post("/api/me/characters", json={"name": "Newguy", "realm": "Whitemane"})
    assert claim.status_code == 201, claim.text

    await _login_officer(member_client, discord_state, discord_id=6299)
    payload = _base_payload(
        sessions=[
            _session_row(
                event_id=str(event_id),
                members=[
                    _member_row("Flipme-Whitemane", "warrior"),
                    _member_row("Ghost1-Whitemane", "priest"),
                    _member_row("Newguy-Whitemane", "druid", standby=True),
                ],
            )
        ]
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    assert response.json()["attendance"]["event_id"] == str(event_id)
    assert response.json()["attendance"]["marked"] == 2  # member_a flipped, walk-in created; member_c untouched

    async with db_sessionmaker() as session:
        signups_stmt = select(EventSignup).where(EventSignup.event_id == event_id)
        signups = (await session.execute(signups_stmt)).scalars().all()
        by_member = {s.member_id: s for s in signups}
        assert by_member[member_a_id].attended is True
        assert by_member[member_c_id].attended is False  # never flipped false -> true
        walk_in = next(s for s in signups if s.member_id not in (member_a_id, member_c_id))
        assert walk_in.is_walk_in is True
        assert walk_in.attended is True
        assert walk_in.bench is True  # standby

        refreshed_event = await session.get(GuildEvent, event_id)
        assert refreshed_event is not None
        assert refreshed_event.attendance_taken_at is not None


# --- bounds / garbage rejection ----------------------------------------------------------------------------


async def test_import_without_sqx1_prefix_is_400(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state)
    response = await member_client.post("/api/epgp/imports", json={"payload": "not an export string at all"})
    assert response.status_code == 400


async def test_import_amount_out_of_bounds_is_400(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state)
    payload = _base_payload(awards=[_award_row(amount=5000)])
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 400


async def test_import_malformed_base64_is_400(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state)
    response = await member_client.post("/api/epgp/imports", json={"payload": "SQX1:not-valid-base64!!!"})
    assert response.status_code == 400


async def test_import_requires_a_session_or_token(member_client: AsyncTestClient) -> None:
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(_base_payload())})
    assert response.status_code == 401


async def test_import_rejects_a_signed_in_non_member(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6301, is_guild_member=False)
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(_base_payload())})
    assert response.status_code == 403


async def test_import_accepts_a_signed_in_non_officer_member_in_member_scope(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=6302, roles=[])
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(_base_payload())})
    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "member"


# --- sync-token auth --------------------------------------------------------------------------------------------


async def test_sync_token_authorizes_import(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=6401)
    created = await member_client.post("/api/epgp/sync-tokens", json={"name": "Raid PC"})
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    assert token.startswith("sqs_")
    assert len(token) == len("sqs_") + 40

    response = await member_client.post(
        "/api/epgp/imports",
        json={"payload": _export_string(_base_payload())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text


async def test_revoked_sync_token_is_401(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=6402)
    created = await member_client.post("/api/epgp/sync-tokens", json={"name": "Revoke me"})
    token = created.json()["token"]
    token_id = created.json()["id"]

    revoke = await member_client.delete(f"/api/epgp/sync-tokens/{token_id}")
    assert revoke.status_code == 204

    response = await member_client.post(
        "/api/epgp/imports",
        json={"payload": _export_string(_base_payload())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


async def test_sync_token_holder_demoted_from_officer_still_imports_member_scope(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Losing officer roles doesn't stop a sync token from importing: the addon import now accepts any guild
    member, scoped to their own linked characters' directory/signups."""
    await _login_officer(member_client, discord_state, discord_id=6403)
    created = await member_client.post("/api/epgp/sync-tokens", json={"name": "Demote me"})
    token = created.json()["token"]

    async with db_sessionmaker() as session:
        member = (await session.execute(select(Member).where(Member.discord_id == 6403))).scalar_one()
        member.roles = []
        await session.commit()

    response = await member_client.post(
        "/api/epgp/imports",
        json={"payload": _export_string(_base_payload())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "member"


async def test_sync_token_holder_no_longer_a_guild_member_is_403_for_imports(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=6404)
    created = await member_client.post("/api/epgp/sync-tokens", json={"name": "Leave guild"})
    token = created.json()["token"]

    async with db_sessionmaker() as session:
        member = (await session.execute(select(Member).where(Member.discord_id == 6404))).scalar_one()
        member.is_guild_member = False
        await session.commit()

    response = await member_client.post(
        "/api/epgp/imports",
        json={"payload": _export_string(_base_payload())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


# --- member-scoped import: applies only the holder's own linked characters' directory/signups ---------------------


async def test_member_import_applies_only_own_linked_directory_and_signups(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=6901, roles=[])
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind="raid", title="Member Import Raid", location="", starts_at=datetime.now(UTC), status="scheduled"
        )
        session.add(event)
        await session.flush()
        member = (await session.execute(select(Member).where(Member.discord_id == 6901))).scalar_one()
        session.add(
            WowCharacter(name="Mine", realm="Whitemane", key="mine-whitemane", member_id=member.id, source="claim")
        )
        await session.commit()
        event_id = event.id

    char_section = {"v": "aaaaaaaa", "at": 1793500000, "d": {"level": 60, "class": "MAGE", "race": "Human"}}
    payload = _base_payload(
        sessions=[_session_row(members=[_member_row("Someoneelse-Whitemane", "warrior")])],
        awards=[_award_row(character="Someoneelse-Whitemane")],
        directory=[
            {"character": "Mine-Whitemane", "sections": {"char": char_section}},
            {"character": "Someoneelse-Whitemane", "sections": {"char": char_section}},
        ],
        signups=[
            {
                "id": "su-mine",
                "event_id": str(event_id),
                "character": "Mine-Whitemane",
                "status": "signed",
                "at": 1793500000,
            },
            {
                "id": "su-other",
                "event_id": str(event_id),
                "character": "Someoneelse-Whitemane",
                "status": "signed",
                "at": 1793500000,
            },
        ],
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "member"
    assert body["directory"]["char"] == {"updated": 1, "skipped": 0}
    assert body["signups"] == {"applied": 1, "skipped_older": 0, "unlinked": 0}
    assert body["sessions"] == {"new": 0, "updated": 0}
    assert body["awards"] == {"new": 0, "updated": 0, "voided": 0}
    assert body["conflicts"] == []
    assert body["attendance"] == {"event_id": None, "marked": 0}

    async with db_sessionmaker() as session:
        audit_count = (await session.execute(select(func.count()).select_from(EpgpImportAudit))).scalar_one()
        assert audit_count == 0, "a member import leaves no officer-import audit row"
        other_char = (
            await session.execute(select(WowCharacter).where(WowCharacter.key == "someoneelse-whitemane"))
        ).scalar_one_or_none()
        assert other_char is None, "the member import never touches a character it doesn't own"
        session_count = (await session.execute(select(func.count()).select_from(RaidSession))).scalar_one()
        assert session_count == 0


async def test_member_import_with_no_linked_characters_returns_zero_counts(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=6902, roles=[])
    payload = _base_payload(
        directory=[
            {
                "character": "Stray-Whitemane",
                "sections": {
                    "char": {"v": "aaaaaaaa", "at": 1793500000, "d": {"level": 60, "class": "MAGE", "race": "Human"}}
                },
            }
        ],
        signups=[
            {
                "id": "su-stray",
                "event_id": str(uuid4()),
                "character": "Stray-Whitemane",
                "status": "signed",
                "at": 1793500000,
            }
        ],
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "member"
    assert body["directory"]["char"] == {"updated": 0, "skipped": 0}
    assert body["signups"] == {"applied": 0, "skipped_older": 0, "unlinked": 0}


async def test_member_sync_token_imports_member_scope(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    token = await _create_member_sync_token(member_client, discord_state, discord_id=6903)
    async with db_sessionmaker() as session:
        member = (await session.execute(select(Member).where(Member.discord_id == 6903))).scalar_one()
        session.add(
            WowCharacter(name="Tok", realm="Whitemane", key="tok-whitemane", member_id=member.id, source="claim")
        )
        await session.commit()

    payload = _base_payload(
        directory=[
            {
                "character": "Tok-Whitemane",
                "sections": {
                    "char": {"v": "aaaaaaaa", "at": 1793500000, "d": {"level": 60, "class": "MAGE", "race": "Human"}}
                },
            }
        ],
    )
    response = await member_client.post(
        "/api/epgp/imports",
        json={"payload": _export_string(payload)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "member"
    assert body["directory"]["char"] == {"updated": 1, "skipped": 0}


async def test_officer_import_has_scope_officer(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=6904)
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(_base_payload())})
    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "officer"


# --- guild members manage their own sync tokens; manual creation stays officer-only ------------------------------


async def test_create_sync_token_stays_officer_only_for_members(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=6410, roles=[])
    response = await member_client.post("/api/epgp/sync-tokens", json={"name": "Not an officer"})
    assert response.status_code == 403


async def test_member_can_list_and_delete_own_sync_tokens(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=6411)
    created = await member_client.post("/api/epgp/sync-tokens", json={"name": "Officer-made token"})
    assert created.status_code == 201, created.text
    token_id = created.json()["id"]

    await login_as(member_client, discord_state, discord_id=6412, roles=[])
    listed = await member_client.get("/api/epgp/sync-tokens")
    assert listed.status_code == 200, listed.text
    assert listed.json() == {"tokens": []}

    created_by_member = await member_client.post("/api/epgp/sync-tokens", json={"name": "Member token"})
    assert created_by_member.status_code == 403

    # a member can't see or delete another member's token
    other_token_delete = await member_client.delete(f"/api/epgp/sync-tokens/{token_id}")
    assert other_token_delete.status_code == 404


# --- sync-tokens/me: a Bearer sync token's own view of itself (SideQuest Companion) ------------------------------


async def test_sync_token_me_profile_for_officer_and_member(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await _login_officer(member_client, discord_state, discord_id=6420)
    officer_token = (await member_client.post("/api/epgp/sync-tokens", json={"name": "Officer token"})).json()["token"]
    officer_me = await member_client.get(
        "/api/epgp/sync-tokens/me", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert officer_me.status_code == 200, officer_me.text
    officer_body = officer_me.json()
    assert officer_body["token_name"] == "Officer token"
    assert officer_body["is_officer"] is True
    assert officer_body["is_guild_member"] is True
    assert officer_body["calendar_url"].endswith(".ics")

    await login_as(member_client, discord_state, discord_id=6421, roles=[])
    # members can't create tokens directly; approve a device sign-in instead to get one scoped to them
    created = await _create_device_authorization(member_client, device_name="Member Device")
    approve = await member_client.post(f"/api/epgp/device-authorizations/{created['user_code']}/approve")
    assert approve.status_code == 204, approve.text
    poll = await member_client.post(
        "/api/epgp/device-authorizations/token", json={"device_code": created["device_code"]}
    )
    member_token = poll.json()["token"]

    member_me = await member_client.get("/api/epgp/sync-tokens/me", headers={"Authorization": f"Bearer {member_token}"})
    assert member_me.status_code == 200, member_me.text
    member_body = member_me.json()
    assert member_body["is_officer"] is False
    assert member_body["is_guild_member"] is True


async def test_sync_token_me_non_guild_member_is_403(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=6422)
    token = (await member_client.post("/api/epgp/sync-tokens", json={"name": "Leaving token"})).json()["token"]

    async with db_sessionmaker() as session:
        member = (await session.execute(select(Member).where(Member.discord_id == 6422))).scalar_one()
        member.is_guild_member = False
        await session.commit()

    response = await member_client.get("/api/epgp/sync-tokens/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


async def test_sync_token_me_unknown_or_revoked_is_401(member_client: AsyncTestClient, discord_state: dict) -> None:
    unknown = await member_client.get(
        "/api/epgp/sync-tokens/me", headers={"Authorization": "Bearer sqs_not-a-real-token"}
    )
    assert unknown.status_code == 401

    await _login_officer(member_client, discord_state, discord_id=6423)
    created = await member_client.post("/api/epgp/sync-tokens", json={"name": "Revoke via DELETE me"})
    token = created.json()["token"]

    delete_me = await member_client.delete("/api/epgp/sync-tokens/me", headers={"Authorization": f"Bearer {token}"})
    assert delete_me.status_code == 204, delete_me.text

    again = await member_client.get("/api/epgp/sync-tokens/me", headers={"Authorization": f"Bearer {token}"})
    assert again.status_code == 401

    delete_again = await member_client.delete("/api/epgp/sync-tokens/me", headers={"Authorization": f"Bearer {token}"})
    assert delete_again.status_code == 401


# --- member character self-claim --------------------------------------------------------------------------------


async def test_member_character_claim_conflicts_409(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6501, roles=[])
    first = await member_client.post("/api/me/characters", json={"name": "Solecharacter", "realm": "Whitemane"})
    assert first.status_code == 201, first.text

    await login_as(member_client, discord_state, discord_id=6502, roles=[])
    second = await member_client.post("/api/me/characters", json={"name": "Solecharacter", "realm": "Whitemane"})
    assert second.status_code == 409


# --- game-import string ----------------------------------------------------------------------------------------


async def test_game_import_string_decodes_back_to_contract_shape(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await _login_officer(member_client, discord_state, discord_id=6601)
    response = await member_client.get("/api/epgp/game-import")
    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload.startswith("SQI1:")
    decoded = json.loads(base64.b64decode(payload[len("SQI1:") :]))
    assert decoded["v"] == 2
    assert "rules" in decoded
    assert decoded["rules"]["ep"]["boss_kill"] == 10
    assert "gp" in decoded["rules"]
    assert "standings" in decoded
    assert "killed_encounters" in decoded
    assert "events" in decoded
    for key in ("members", "news", "sheets", "crafters", "recipe_names"):
        assert key in decoded


async def test_game_import_includes_non_role_kind_event(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A scheduled social/other event must appear in the SQI1: import, not just raid/dungeon/world_boss."""
    await _login_officer(member_client, discord_state, discord_id=6610)
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind="other",
            title="The Adventure Begins - Discord hang out",
            location="",
            starts_at=PAST,
            status="scheduled",
        )
        session.add(event)
        await session.commit()
        event_id = str(event.id)

    response = await member_client.get("/api/epgp/game-import")
    assert response.status_code == 200
    decoded = json.loads(base64.b64decode(response.json()["payload"][len("SQI1:") :]))
    kinds_by_id = {e["id"]: e["kind"] for e in decoded["events"]}
    assert kinds_by_id.get(event_id) == "other"


async def test_game_import_carries_roleless_signup_for_non_role_event(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A member's Going/Maybe/Can't answer on a social event round-trips without class/role."""
    await _login_officer(member_client, discord_state, discord_id=6611)
    async with db_sessionmaker() as session:
        event = GuildEvent(kind="social", title="Game Night", location="", starts_at=PAST, status="scheduled")
        session.add(event)
        await session.flush()
        member = Member(discord_id=6612, username="roleless", is_guild_member=True)
        session.add(member)
        await session.flush()
        session.add(EventSignup(event_id=event.id, member_id=member.id, character="Barehand", status="signed"))
        await session.commit()
        event_id = str(event.id)

    response = await member_client.get("/api/epgp/game-import")
    decoded = json.loads(base64.b64decode(response.json()["payload"][len("SQI1:") :]))
    event_payload = next(e for e in decoded["events"] if e["id"] == event_id)
    assert len(event_payload["signups"]) == 1
    signup = event_payload["signups"][0]
    assert signup["character"] == "Barehand"
    assert signup["status"] == "signed"
    assert signup["class"] is None
    assert signup["role"] is None


async def test_game_import_excludes_incomplete_signup_for_role_kind_event(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A raid/dungeon/world_boss sign-up missing class or role is still dropped, unlike non-role kinds."""
    await _login_officer(member_client, discord_state, discord_id=6613)
    async with db_sessionmaker() as session:
        event = GuildEvent(kind="raid", title="Molten Core", location="", starts_at=PAST, status="scheduled")
        session.add(event)
        await session.flush()
        member = Member(discord_id=6614, username="incomplete", is_guild_member=True)
        session.add(member)
        await session.flush()
        session.add(EventSignup(event_id=event.id, member_id=member.id, character="Halfsigned", status="signed"))
        await session.commit()
        event_id = str(event.id)

    response = await member_client.get("/api/epgp/game-import")
    decoded = json.loads(base64.b64decode(response.json()["payload"][len("SQI1:") :]))
    event_payload = next(e for e in decoded["events"] if e["id"] == event_id)
    assert event_payload["signups"] == []


async def test_game_import_lists_recent_past_events_newest_first(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Events that started before the upcoming window, within 30 days and not cancelled, go to past_events."""
    await _login_officer(member_client, discord_state, discord_id=6615)
    now = datetime.now(UTC)
    async with db_sessionmaker() as session:
        events = {
            title: GuildEvent(kind="social", title=title, location="", starts_at=now - age, status=status)
            for title, age, status in (
                ("Last week", timedelta(days=7), "completed"),
                ("Yesterday", timedelta(days=1), "scheduled"),
                ("Called off", timedelta(days=2), "cancelled"),
                ("Too old", timedelta(days=31), "completed"),
                ("Tonight", timedelta(hours=1), "scheduled"),
            )
        }
        session.add_all(events.values())
        await session.commit()

    response = await member_client.get("/api/epgp/game-import")
    decoded = json.loads(base64.b64decode(response.json()["payload"][len("SQI1:") :]))
    assert [e["title"] for e in decoded["past_events"]] == ["Yesterday", "Last week"]
    assert [e["title"] for e in decoded["events"]] == ["Tonight"]


async def test_sync_token_authorizes_game_import(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=6602)
    created = await member_client.post("/api/epgp/sync-tokens", json={"name": "Raid PC"})
    token = created.json()["token"]

    response = await member_client.get("/api/epgp/game-import", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert response.json()["payload"].startswith("SQI1:")

    async with db_sessionmaker() as session:
        row = (
            await session.execute(select(EpgpSyncToken).where(EpgpSyncToken.id == created.json()["id"]))
        ).scalar_one()
        assert row.last_used_at is not None


async def test_revoked_sync_token_is_401_for_game_import(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=6603)
    created = await member_client.post("/api/epgp/sync-tokens", json={"name": "Revoke me"})
    token = created.json()["token"]
    token_id = created.json()["id"]

    revoke = await member_client.delete(f"/api/epgp/sync-tokens/{token_id}")
    assert revoke.status_code == 204

    response = await member_client.get("/api/epgp/game-import", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_unknown_sync_token_is_401_for_game_import(member_client: AsyncTestClient) -> None:
    response = await member_client.get(
        "/api/epgp/game-import", headers={"Authorization": "Bearer sqs_not-a-real-token"}
    )
    assert response.status_code == 401


async def test_sync_token_holder_no_longer_officer_is_403_for_game_import(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=6604)
    created = await member_client.post("/api/epgp/sync-tokens", json={"name": "Demote me"})
    token = created.json()["token"]

    async with db_sessionmaker() as session:
        member = (await session.execute(select(Member).where(Member.discord_id == 6604))).scalar_one()
        member.roles = []
        await session.commit()

    response = await member_client.get("/api/epgp/game-import", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


# --- real addon fixture: Lua drops nil keys, so this exercises absent (not null) optional fields ------------------


async def test_real_addon_fixture_imports_successfully_and_is_idempotent(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    raw_text = (FIXTURES_DIR / "export_v1.txt").read_text()
    await _login_officer(member_client, discord_state, discord_id=6701)

    first = await member_client.post("/api/epgp/imports", json={"payload": raw_text})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["sessions"]["new"] == 1
    assert body["encounters"]["new"] == 3
    assert body["loot"]["new"] == 2
    assert body["awards"]["new"] == 22

    second = await member_client.post("/api/epgp/imports", json={"payload": raw_text})
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["sessions"]["new"] == 0
    assert second_body["encounters"]["new"] == 0
    assert second_body["loot"]["new"] == 0
    assert second_body["awards"]["new"] == 0


async def test_loot_can_be_filtered_to_one_item(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=6702)
    await member_client.post("/api/epgp/imports", json={"payload": (FIXTURES_DIR / "export_v1.txt").read_text()})
    every = (await member_client.get("/api/epgp/loot")).json()["items"]
    item_ids = {item["item_id"] for item in every}
    assert len(item_ids) == 2
    wanted = min(item_ids)

    filtered = (await member_client.get("/api/epgp/loot", params={"item_id": wanted})).json()["items"]

    assert [item["item_id"] for item in filtered] == [wanted]


# --- device authorizations: browser sign-in for SideQuest Companion ------------------------------------------


async def _create_device_authorization(client: AsyncTestClient, *, device_name: str = "Office PC") -> dict[str, Any]:
    response = await client.post("/api/epgp/device-authorizations", json={"device_name": device_name})
    assert response.status_code == 201, response.text
    return response.json()


async def _clear_last_polled(db_sessionmaker: async_sessionmaker[AsyncSession], user_code: str) -> None:
    """Simulate the poll interval having passed, without a real sleep."""
    async with db_sessionmaker() as session:
        row = (
            await session.execute(
                select(EpgpDeviceAuthorization).where(EpgpDeviceAuthorization.user_code == user_code.replace("-", ""))
            )
        ).scalar_one()
        row.last_polled_at = None
        await session.commit()


async def test_device_authorization_full_flow(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    created = await _create_device_authorization(member_client, device_name="Office PC")
    assert len(created["device_code"]) >= 32
    assert len(created["user_code"]) == 9  # XXXX-XXXX
    assert created["user_code"][4] == "-"
    assert created["verification_uri"].endswith("/companion/authorize/")
    assert created["verification_uri_complete"] == f"{created['verification_uri']}?code={created['user_code']}"
    assert created["expires_in"] == 600
    assert created["interval"] == 5
    device_code = created["device_code"]
    user_code = created["user_code"]

    pending = await member_client.post("/api/epgp/device-authorizations/token", json={"device_code": device_code})
    assert pending.status_code == 200
    assert pending.json() == {"status": "pending", "token": None, "name": None}

    slow = await member_client.post("/api/epgp/device-authorizations/token", json={"device_code": device_code})
    assert slow.status_code == 200
    assert slow.json()["status"] == "slow_down"

    await _login_officer(member_client, discord_state, discord_id=6801)
    status = await member_client.get(f"/api/epgp/device-authorizations/{user_code}")
    assert status.status_code == 200, status.text
    assert status.json() == {
        "user_code": user_code,
        "device_name": "Office PC",
        "created_at": status.json()["created_at"],
        "expires_at": status.json()["expires_at"],
        "status": "pending",
    }

    approve = await member_client.post(f"/api/epgp/device-authorizations/{user_code}/approve")
    assert approve.status_code == 204, approve.text

    status_after_approve = await member_client.get(f"/api/epgp/device-authorizations/{user_code}")
    assert status_after_approve.json()["status"] == "approved"

    await _clear_last_polled(db_sessionmaker, user_code)
    approved_poll = await member_client.post("/api/epgp/device-authorizations/token", json={"device_code": device_code})
    assert approved_poll.status_code == 200
    approved_body = approved_poll.json()
    assert approved_body["status"] == "approved"
    assert approved_body["token"].startswith("sqs_")
    assert approved_body["name"] == "SideQuest Companion on Office PC"

    import_response = await member_client.post(
        "/api/epgp/imports",
        json={"payload": _export_string(_base_payload())},
        headers={"Authorization": f"Bearer {approved_body['token']}"},
    )
    assert import_response.status_code == 200, import_response.text

    again = await member_client.post("/api/epgp/device-authorizations/token", json={"device_code": device_code})
    assert again.status_code == 200
    assert again.json() == {"status": "expired", "token": None, "name": None}


async def test_device_authorization_deny(member_client: AsyncTestClient, discord_state: dict) -> None:
    created = await _create_device_authorization(member_client, device_name="Raid Laptop")
    device_code = created["device_code"]
    user_code = created["user_code"]

    await _login_officer(member_client, discord_state, discord_id=6802)
    deny = await member_client.post(f"/api/epgp/device-authorizations/{user_code}/deny")
    assert deny.status_code == 204, deny.text

    status = await member_client.get(f"/api/epgp/device-authorizations/{user_code}")
    assert status.json()["status"] == "denied"

    poll = await member_client.post("/api/epgp/device-authorizations/token", json={"device_code": device_code})
    assert poll.status_code == 200
    assert poll.json() == {"status": "denied", "token": None, "name": None}

    # already denied: approving or denying again is a conflict
    deny_again = await member_client.post(f"/api/epgp/device-authorizations/{user_code}/deny")
    assert deny_again.status_code == 409
    approve_after_deny = await member_client.post(f"/api/epgp/device-authorizations/{user_code}/approve")
    assert approve_after_deny.status_code == 409


async def test_device_authorization_expires(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    created = await _create_device_authorization(member_client, device_name="Stale Device")
    device_code = created["device_code"]
    user_code = created["user_code"]

    async with db_sessionmaker() as session:
        row = (
            await session.execute(
                select(EpgpDeviceAuthorization).where(EpgpDeviceAuthorization.user_code == user_code.replace("-", ""))
            )
        ).scalar_one()
        row.expires_at = PAST
        await session.commit()

    poll = await member_client.post("/api/epgp/device-authorizations/token", json={"device_code": device_code})
    assert poll.status_code == 200
    assert poll.json() == {"status": "expired", "token": None, "name": None}

    await _login_officer(member_client, discord_state, discord_id=6803)
    status = await member_client.get(f"/api/epgp/device-authorizations/{user_code}")
    assert status.json()["status"] == "expired"

    approve = await member_client.post(f"/api/epgp/device-authorizations/{user_code}/approve")
    assert approve.status_code == 409


async def test_unknown_device_user_code_is_404(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=6804)
    get_response = await member_client.get("/api/epgp/device-authorizations/ZZZZ-ZZZZ")
    assert get_response.status_code == 404
    approve_response = await member_client.post("/api/epgp/device-authorizations/ZZZZ-ZZZZ/approve")
    assert approve_response.status_code == 404


async def test_unknown_device_code_poll_is_expired(member_client: AsyncTestClient) -> None:
    poll = await member_client.post(
        "/api/epgp/device-authorizations/token", json={"device_code": "not-a-real-device-code"}
    )
    assert poll.status_code == 200
    assert poll.json() == {"status": "expired", "token": None, "name": None}


async def test_device_authorization_member_can_view_and_approve(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    """Any guild member, not just an officer, can view and approve a pending device sign-in."""
    created = await _create_device_authorization(member_client, device_name="Someone's PC")
    user_code = created["user_code"]

    await login_as(member_client, discord_state, discord_id=6805, roles=[])
    get_response = await member_client.get(f"/api/epgp/device-authorizations/{user_code}")
    assert get_response.status_code == 200, get_response.text
    approve_response = await member_client.post(f"/api/epgp/device-authorizations/{user_code}/approve")
    assert approve_response.status_code == 204, approve_response.text


async def test_device_authorization_non_guild_member_cannot_view_or_approve(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    created = await _create_device_authorization(member_client, device_name="Outsider's PC")
    user_code = created["user_code"]

    await login_as(member_client, discord_state, discord_id=6808, is_guild_member=False)
    get_response = await member_client.get(f"/api/epgp/device-authorizations/{user_code}")
    assert get_response.status_code == 403
    approve_response = await member_client.post(f"/api/epgp/device-authorizations/{user_code}/approve")
    assert approve_response.status_code == 403


async def test_device_authorization_approver_left_guild_before_poll_is_denied(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Losing officer access alone doesn't deny a pending approval; leaving the guild entirely does."""
    created = await _create_device_authorization(member_client, device_name="Departing Member's PC")
    device_code = created["device_code"]
    user_code = created["user_code"]

    await _login_officer(member_client, discord_state, discord_id=6806)
    approve = await member_client.post(f"/api/epgp/device-authorizations/{user_code}/approve")
    assert approve.status_code == 204, approve.text

    async with db_sessionmaker() as session:
        member = (await session.execute(select(Member).where(Member.discord_id == 6806))).scalar_one()
        member.is_guild_member = False
        tokens_before = (await session.execute(select(func.count()).select_from(EpgpSyncToken))).scalar_one()
        await session.commit()

    await _clear_last_polled(db_sessionmaker, user_code)
    poll = await member_client.post("/api/epgp/device-authorizations/token", json={"device_code": device_code})
    assert poll.status_code == 200
    assert poll.json() == {"status": "denied", "token": None, "name": None}

    async with db_sessionmaker() as session:
        tokens_after = (await session.execute(select(func.count()).select_from(EpgpSyncToken))).scalar_one()
    assert tokens_after == tokens_before


async def test_device_authorization_member_approval_token_imports_member_scope_but_not_game_import(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A member (non-officer) can approve a sign-in; the minted token imports in member scope, but still can't
    read the officer-only game-import string."""
    created = await _create_device_authorization(member_client, device_name="Member's PC")
    device_code = created["device_code"]
    user_code = created["user_code"]

    await login_as(member_client, discord_state, discord_id=6809, roles=[])
    approve = await member_client.post(f"/api/epgp/device-authorizations/{user_code}/approve")
    assert approve.status_code == 204, approve.text

    await _clear_last_polled(db_sessionmaker, user_code)
    poll = await member_client.post("/api/epgp/device-authorizations/token", json={"device_code": device_code})
    assert poll.status_code == 200
    token = poll.json()["token"]
    assert token.startswith("sqs_")

    import_response = await member_client.post(
        "/api/epgp/imports",
        json={"payload": _export_string(_base_payload())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert import_response.status_code == 200, import_response.text
    assert import_response.json()["scope"] == "member"

    game_import_response = await member_client.get(
        "/api/epgp/game-import", headers={"Authorization": f"Bearer {token}"}
    )
    assert game_import_response.status_code == 403


async def test_device_authorization_user_code_normalizes_case_and_dash(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    created = await _create_device_authorization(member_client, device_name="Case Test PC")
    user_code = created["user_code"]
    messy = user_code.replace("-", "").lower()

    await _login_officer(member_client, discord_state, discord_id=6807)
    status = await member_client.get(f"/api/epgp/device-authorizations/{messy}")
    assert status.status_code == 200, status.text
    assert status.json()["user_code"] == user_code


async def test_device_authorization_device_name_blank_is_400(member_client: AsyncTestClient) -> None:
    response = await member_client.post("/api/epgp/device-authorizations", json={"device_name": "   "})
    assert response.status_code == 400


async def test_device_authorization_device_name_control_chars_is_400(member_client: AsyncTestClient) -> None:
    response = await member_client.post("/api/epgp/device-authorizations", json={"device_name": "bad\x00name"})
    assert response.status_code == 400


async def test_device_authorization_device_name_too_long_is_400(member_client: AsyncTestClient) -> None:
    response = await member_client.post("/api/epgp/device-authorizations", json={"device_name": "x" * 61})
    assert response.status_code == 400


async def test_device_authorization_pending_cap_is_429(member_client: AsyncTestClient) -> None:
    for i in range(500):
        response = await member_client.post("/api/epgp/device-authorizations", json={"device_name": f"Device {i}"})
        assert response.status_code == 201, response.text
    over_cap = await member_client.post("/api/epgp/device-authorizations", json={"device_name": "One too many"})
    assert over_cap.status_code == 429


# --- loot council -----------------------------------------------------------------------------------------


async def _add_council_award(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    external_id: str,
    at: datetime = PAST,
    voided_at: datetime | None = None,
    council_posted_at: datetime | None = None,
    council_void_posted_at: datetime | None = None,
) -> UUID:
    async with db_sessionmaker() as session:
        row = LootAward(
            external_id=external_id,
            item_id=19019,
            item_name="Thunderfury, Blessed Blade of the Windseeker",
            quality=4,
            inv_type="INVTYPE_WEAPONMAINHAND",
            response="council",
            gp=300,
            at=at,
            officer=RECORDER,
            voided_at=voided_at,
            council_reason="Best in slot for progression.",
            council_kind="legendary",
            council_posted_at=council_posted_at,
            council_void_posted_at=council_void_posted_at,
        )
        session.add(row)
        await session.commit()
        return row.id


async def test_import_stores_council_reason_and_kind_and_keeps_posted_stamp_on_reimport(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state)
    payload = _base_payload(
        sessions=[_session_row(members=[_member_row("Tank1-Whitemane", "warrior")])], loot=[_loot_row()]
    )
    first = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert first.status_code == 200, first.text

    async with db_sessionmaker() as session:
        award = (await session.execute(select(LootAward).where(LootAward.external_id == "L1"))).scalar_one()
        assert award.council_reason == "Best in slot for progression."
        assert award.council_kind == "legendary"
        assert award.council_posted_at is None
        award.council_posted_at = PAST  # simulate the bot having already posted it
        await session.commit()

    second = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert second.status_code == 200, second.text

    async with db_sessionmaker() as session:
        award = (await session.execute(select(LootAward).where(LootAward.external_id == "L1"))).scalar_one()
        assert award.council_reason == "Best in slot for progression."
        assert award.council_kind == "legendary"
        assert award.council_posted_at is not None  # a re-import never clears it


async def test_pending_council_log_returns_decisions_and_posted_voids_but_skips_voided_before_post(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    decision_id = await _add_council_award(db_sessionmaker, external_id="L-decision", at=PAST)
    await _add_council_award(
        db_sessionmaker, external_id="L-voided-early", at=PAST, voided_at=PAST + timedelta(minutes=1)
    )
    void_id = await _add_council_award(
        db_sessionmaker,
        external_id="L-voided-late",
        at=PAST,
        voided_at=PAST + timedelta(minutes=5),
        council_posted_at=PAST,
    )

    response = await client.get(f"/api/guilds/{GUILD_ID}/loot/council/pending")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    by_id = {item["loot_id"]: item for item in items}
    assert set(by_id) == {str(decision_id), str(void_id)}
    assert by_id[str(decision_id)]["kind"] == "decision"
    assert by_id[str(decision_id)]["council_reason"] == "Best in slot for progression."
    assert by_id[str(decision_id)]["council_kind"] == "legendary"
    assert by_id[str(void_id)]["kind"] == "void"


async def test_ack_council_posted_is_idempotent(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    loot_id = await _add_council_award(db_sessionmaker, external_id="L-ack")

    first = await client.post(f"/api/guilds/{GUILD_ID}/loot/council/{loot_id}/posted", json={"kind": "decision"})
    assert first.status_code == 204, first.text
    second = await client.post(f"/api/guilds/{GUILD_ID}/loot/council/{loot_id}/posted", json={"kind": "decision"})
    assert second.status_code == 204, second.text

    async with db_sessionmaker() as session:
        award = await session.get(LootAward, loot_id)
        assert award is not None
        assert award.council_posted_at is not None

    pending = await client.get(f"/api/guilds/{GUILD_ID}/loot/council/pending")
    assert pending.json()["items"] == []


async def test_council_log_routes_404_for_another_guild(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    loot_id = await _add_council_award(db_sessionmaker, external_id="L-other-guild")
    other_guild = GUILD_ID + 1

    pending = await client.get(f"/api/guilds/{other_guild}/loot/council/pending")
    assert pending.status_code == 404

    posted = await client.post(f"/api/guilds/{other_guild}/loot/council/{loot_id}/posted", json={"kind": "decision"})
    assert posted.status_code == 404


async def test_public_loot_api_exposes_council_reason_and_kind(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _add_council_award(db_sessionmaker, external_id="L-public")

    response = await member_client.get("/api/epgp/loot")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["response"] == "council"
    assert items[0]["council_reason"] == "Best in slot for progression."
    assert items[0]["council_kind"] == "legendary"
