"""EPGP: decay math, standings, the SQX1: import (idempotency, voiding, conflicts, auto-link, attendance hand-off),
bounds rejection, sync-token auth, member character self-claim, and the SQI1: game-import string."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from sidequest_api.domain.epgp.services import decayed_amount, resets_since
from sidequest_common.models import (
    EpgpLedgerEntry,
    EpgpSyncToken,
    EventSignup,
    GuildEvent,
    Member,
    RaidSession,
    WowCharacter,
)
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


async def _login_officer(client: AsyncTestClient, discord_state: dict, *, discord_id: int = 100) -> None:
    response = await login_as(client, discord_state, discord_id=discord_id, roles=[OFFICER_ROLE_ID])
    assert response.status_code == 302, response.text


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


async def test_import_requires_officer_or_token(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6301, roles=[])
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(_base_payload())})
    assert response.status_code == 403


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


async def test_sync_token_holder_no_longer_officer_is_403(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
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
    assert response.status_code == 403


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
