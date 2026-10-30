"""Guild hub v2: the SQX1: v2 import sections, the SQI1: v2 game-import shape, and the /api/guild/* + officer
recruiting/notes HTTP endpoints. See ``local://addon-contract-v2.md``."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import (
    CharacterProfession,
    GuildAnnouncement,
    GuildNewsEvent,
    GuildRecruit,
    GuildRosterSnapshot,
    Member,
    MemberNote,
    RecruitVote,
    WowCharacter,
)
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

RECORDER = "Officername-Whitemane"
EXPORTED_AT = 1793500000
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _export_string(payload: dict) -> str:
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"SQX1:{encoded}"


def _base_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "v": 2,
        "addon_version": "1.0.0",
        "exported_at": EXPORTED_AT,
        "guild": "SideQuest",
        "realm": "Whitemane",
        "recorder": RECORDER,
        "sessions": [],
        "encounters": [],
        "loot": [],
        "awards": [],
        "roster": None,
        "professions": [],
        "signups": [],
        "bank": [],
        "announcements": [],
        "recruits": [],
        "member_notes": [],
    }
    payload.update(overrides)
    return payload


async def _login_officer(client: AsyncTestClient, discord_state: dict, *, discord_id: int = 100) -> None:
    response = await login_as(client, discord_state, discord_id=discord_id, roles=[OFFICER_ROLE_ID])
    assert response.status_code == 302, response.text


# --- roster: level-up milestones, left_guild_at sweep -----------------------------------------------------------


async def test_roster_import_upserts_and_level_up_news_only_at_multiples_of_ten(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7001)
    payload = _base_payload(
        roster={
            "taken_at": EXPORTED_AT,
            "members": [
                {"character": "Leveler-Whitemane", "rank": "Member", "rank_index": 2, "level": 15, "class": "mage"}
            ],
        }
    )
    first = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert first.status_code == 200, first.text
    assert first.json()["roster"]["updated"] == 1

    async with db_sessionmaker() as session:
        news = (await session.execute(select(GuildNewsEvent).where(GuildNewsEvent.kind == "level"))).scalars().all()
        assert news == []  # 15 is not a multiple of 10: no news yet

    # Level up to 20 (a milestone): exactly one level-up news row.
    second_payload = _base_payload(
        roster={
            "taken_at": EXPORTED_AT + 3600,
            "members": [
                {"character": "Leveler-Whitemane", "rank": "Member", "rank_index": 2, "level": 20, "class": "mage"}
            ],
        }
    )
    second = await member_client.post("/api/epgp/imports", json={"payload": _export_string(second_payload)})
    assert second.status_code == 200, second.text

    async with db_sessionmaker() as session:
        news = (await session.execute(select(GuildNewsEvent).where(GuildNewsEvent.kind == "level"))).scalars().all()
        assert len(news) == 1
        assert "level 20" in news[0].text

    # Re-importing the identical level-20 sweep must not duplicate the news row.
    third = await member_client.post("/api/epgp/imports", json={"payload": _export_string(second_payload)})
    assert third.status_code == 200, third.text
    async with db_sessionmaker() as session:
        news = (await session.execute(select(GuildNewsEvent).where(GuildNewsEvent.kind == "level"))).scalars().all()
        assert len(news) == 1


async def test_roster_import_marks_left_guild_at_after_thirty_days(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7002)
    first = await member_client.post(
        "/api/epgp/imports",
        json={
            "payload": _export_string(
                _base_payload(
                    roster={
                        "taken_at": EXPORTED_AT,
                        "members": [{"character": "Ghost-Whitemane", "rank": "Member", "rank_index": 2, "level": 60}],
                    }
                )
            )
        },
    )
    assert first.status_code == 200, first.text

    async with db_sessionmaker() as session:
        character = (
            await session.execute(select(WowCharacter).where(WowCharacter.key == "ghost-whitemane"))
        ).scalar_one()
        snapshot = (
            await session.execute(select(GuildRosterSnapshot).where(GuildRosterSnapshot.character_id == character.id))
        ).scalar_one()
        assert snapshot.left_guild_at is None

    # A later sweep (31 days on) that doesn't mention Ghost ages its snapshot past the cutoff.
    later_taken_at = EXPORTED_AT + int(timedelta(days=31).total_seconds())
    second = await member_client.post(
        "/api/epgp/imports",
        json={
            "payload": _export_string(
                _base_payload(
                    roster={
                        "taken_at": later_taken_at,
                        "members": [{"character": "Other-Whitemane", "rank": "Member", "rank_index": 2, "level": 60}],
                    }
                )
            )
        },
    )
    assert second.status_code == 200, second.text

    async with db_sessionmaker() as session:
        character = (
            await session.execute(select(WowCharacter).where(WowCharacter.key == "ghost-whitemane"))
        ).scalar_one()
        snapshot = (
            await session.execute(select(GuildRosterSnapshot).where(GuildRosterSnapshot.character_id == character.id))
        ).scalar_one()
        assert snapshot.left_guild_at is not None


# --- professions: upsert, recipes replaced wholesale -------------------------------------------------------------


async def test_professions_import_upserts_skill_and_replaces_recipes(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7003)
    payload = _base_payload(
        professions=[
            {
                "character": "Crafter-Whitemane",
                "profession": "Blacksmithing",
                "skill": 100,
                "max_skill": 150,
                "scanned_at": EXPORTED_AT,
                "recipes": [{"id": 2662, "name": "Copper Chain Pants", "item_id": 2852}],
            }
        ]
    )
    first = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert first.status_code == 200, first.text
    assert first.json()["professions"]["updated"] == 1

    payload2 = _base_payload(
        professions=[
            {
                "character": "Crafter-Whitemane",
                "profession": "Blacksmithing",
                "skill": 150,
                "max_skill": 150,
                "scanned_at": EXPORTED_AT + 100,
                "recipes": [{"id": 2663, "name": "Heavy Grinding Stone", "item_id": 2853}],
            }
        ]
    )
    second = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload2)})
    assert second.status_code == 200, second.text

    async with db_sessionmaker() as session:
        rows = (await session.execute(select(CharacterProfession))).scalars().all()
        assert len(rows) == 1
        assert rows[0].skill == 150

    response = await member_client.get("/api/guild/crafters", params={"q": "Heavy Grinding Stone"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["recipe_name"] == "Heavy Grinding Stone"
    assert body["results"][0]["crafters"][0]["character"] == "crafter-whitemane"
    # The old recipe was replaced, not accumulated.
    old = await member_client.get("/api/guild/crafters", params={"q": "Copper Chain Pants"})
    assert old.json()["results"] == []


async def test_crafters_search_matches_profession_substring(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7004)
    payload = _base_payload(
        professions=[
            {
                "character": "Tailor-Whitemane",
                "profession": "Tailoring",
                "skill": 50,
                "max_skill": 150,
                "scanned_at": EXPORTED_AT,
                "recipes": [{"id": 9001, "name": "Bolt of Linen Cloth", "item_id": 9002}],
            }
        ]
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text

    search = await member_client.get("/api/guild/crafters", params={"profession": "Tailoring"})
    assert search.status_code == 200, search.text
    assert any(row["profession"] == "Tailoring" for row in search.json()["professions"])


# --- signups: newest-wins, unlinked skipped -----------------------------------------------------------------------


async def test_signups_v2_newest_wins_and_unlinked_characters_are_skipped(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    from sidequest_common.models import GuildEvent

    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind="raid", title="Signup Test Raid", location="", starts_at=datetime.now(UTC), status="scheduled"
        )
        session.add(event)
        await session.flush()
        member = Member(discord_id=7101, username="signuptester", is_guild_member=True)
        session.add(member)
        await session.flush()
        character = WowCharacter(
            name="Linked", realm="Whitemane", key="linked-whitemane", member_id=member.id, source="claim"
        )
        session.add(character)
        await session.commit()
        event_id, member_id = event.id, member.id

    await _login_officer(member_client, discord_state, discord_id=7102)
    now = datetime.now(UTC)
    older_at = int((now - timedelta(hours=2)).timestamp())
    stale_at = int((now - timedelta(hours=3)).timestamp())
    older = await member_client.post(
        "/api/epgp/imports",
        json={
            "payload": _export_string(
                _base_payload(
                    signups=[
                        {
                            "id": "su-1",
                            "event_id": str(event_id),
                            "character": "Linked-Whitemane",
                            "status": "signed",
                            "role": "tank",
                            "class": "warrior",
                            "at": older_at,
                        },
                        {
                            "id": "su-unlinked",
                            "event_id": str(event_id),
                            "character": "Nobody-Whitemane",
                            "status": "signed",
                            "at": older_at,
                        },
                    ]
                )
            )
        },
    )
    assert older.status_code == 200, older.text
    assert older.json()["signups"]["applied"] == 1
    assert older.json()["signups"]["unlinked"] == 1

    # A stale (older ``at``) re-send must not override the newer site/game state.
    stale = await member_client.post(
        "/api/epgp/imports",
        json={
            "payload": _export_string(
                _base_payload(
                    signups=[
                        {
                            "id": "su-1b",
                            "event_id": str(event_id),
                            "character": "Linked-Whitemane",
                            "status": "tentative",
                            "at": stale_at,
                        }
                    ]
                )
            )
        },
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["signups"]["skipped_older"] == 1

    async with db_sessionmaker() as session:
        from sidequest_common.models import EventSignup

        signup = (
            await session.execute(
                select(EventSignup).where(EventSignup.event_id == event_id, EventSignup.member_id == member_id)
            )
        ).scalar_one()
        assert signup.status == "signed"  # the stale update never applied


# --- bank: insert-only, deduped by id ------------------------------------------------------------------------------


async def test_bank_import_is_insert_only_deduped_by_id(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7201)
    row = {
        "id": "bank-1",
        "at": EXPORTED_AT,
        "character": "Banker-Whitemane",
        "kind": "deposit",
        "item_id": 2589,
        "item_name": "Linen Cloth",
        "count": 20,
        "money": 0,
        "tab": 1,
    }
    first = await member_client.post("/api/epgp/imports", json={"payload": _export_string(_base_payload(bank=[row]))})
    assert first.status_code == 200, first.text
    assert first.json()["bank"]["new"] == 1

    second = await member_client.post("/api/epgp/imports", json={"payload": _export_string(_base_payload(bank=[row]))})
    assert second.status_code == 200, second.text
    assert second.json()["bank"]["new"] == 0  # re-import is a no-op

    bank_page = await member_client.get("/api/guild/bank")
    assert bank_page.status_code == 200, bank_page.text
    assert len(bank_page.json()["rows"]) == 1


# --- announcements: queue -> pending -> posted ----------------------------------------------------------------------


async def test_announcement_import_queues_for_bot_then_bot_marks_it_posted(
    member_client: AsyncTestClient, client: AsyncTestClient, discord_state: dict
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7301)
    response = await member_client.post(
        "/api/epgp/imports",
        json={
            "payload": _export_string(
                _base_payload(
                    announcements=[
                        {
                            "id": "ann-1",
                            "text": "Flasks for Friday please",
                            "officer": RECORDER,
                            "at": EXPORTED_AT,
                            "discord": True,
                        }
                    ]
                )
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["announcements"]["new"] == 1

    announcements_page = await member_client.get("/api/guild/announcements")
    assert announcements_page.status_code == 200, announcements_page.text
    items = announcements_page.json()["items"]
    assert len(items) == 1
    assert items[0]["posted_at"] is None
    announcement_id = items[0]["id"]

    from tests.conftest import GUILD_ID

    pending = await client.get(f"/api/guilds/{GUILD_ID}/announcements/pending")
    assert pending.status_code == 200, pending.text
    assert len(pending.json()["items"]) == 1
    assert pending.json()["items"][0]["id"] == announcement_id

    posted = await client.post(
        f"/api/guilds/{GUILD_ID}/announcements/{announcement_id}/posted", json={"message_id": 999}
    )
    assert posted.status_code == 200, posted.text

    pending_after = await client.get(f"/api/guilds/{GUILD_ID}/announcements/pending")
    assert pending_after.json()["items"] == []

    announcements_after = await member_client.get("/api/guild/announcements")
    assert announcements_after.json()["items"][0]["posted_at"] is not None


async def test_site_officer_announcement_appears_in_news(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7302)
    response = await member_client.post(
        "/api/guild/announcements", json={"text": "Raid moved to 8pm", "discord": False}
    )
    assert response.status_code == 201, response.text
    assert response.json()["source"] == "site"

    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(GuildAnnouncement).where(GuildAnnouncement.source == "site"))).scalars().all()
        )
        assert len(rows) == 1
        news = (
            (await session.execute(select(GuildNewsEvent).where(GuildNewsEvent.kind == "announcement"))).scalars().all()
        )
        assert len(news) == 1


# --- recruits: upsert by id, votes upsert per officer -----------------------------------------------------------


async def test_recruits_import_upserts_and_votes_upsert_per_officer(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7401)
    base_recruit = {
        "id": "rec-1",
        "character": "Hopeful-Whitemane",
        "class": "mage",
        "status": "applicant",
        "note": "Found in LFG",
        "checklist": {"talked": True, "gear_check": False, "first_raid": False, "vouched": False},
        "votes": [{"officer": "Officer1-Whitemane", "vote": "yes", "at": EXPORTED_AT}],
        "at": EXPORTED_AT,
    }
    first = await member_client.post(
        "/api/epgp/imports", json={"payload": _export_string(_base_payload(recruits=[base_recruit]))}
    )
    assert first.status_code == 200, first.text
    assert first.json()["recruits"]["new"] == 1

    updated_recruit = dict(base_recruit)
    updated_recruit["status"] = "trial"
    updated_recruit["votes"] = [{"officer": "Officer1-Whitemane", "vote": "no", "at": EXPORTED_AT + 10}]
    second = await member_client.post(
        "/api/epgp/imports", json={"payload": _export_string(_base_payload(recruits=[updated_recruit]))}
    )
    assert second.status_code == 200, second.text
    assert second.json()["recruits"]["updated"] == 1

    async with db_sessionmaker() as session:
        recruit = (await session.execute(select(GuildRecruit).where(GuildRecruit.external_id == "rec-1"))).scalar_one()
        assert recruit.status == "trial"
        votes = (await session.execute(select(RecruitVote).where(RecruitVote.recruit_id == recruit.id))).scalars().all()
        assert len(votes) == 1  # upserted, not duplicated
        assert votes[0].vote == "no"

    recruits_list = await member_client.get("/api/epgp/recruits/")
    assert recruits_list.status_code == 200, recruits_list.text
    assert recruits_list.json()["recruits"][0]["status"] == "trial"


async def test_recruit_trial_sets_linked_members_raid_status(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=7501, username="futuretrial", is_guild_member=True)
        session.add(member)
        await session.flush()
        character = WowCharacter(
            name="Trialer", realm="Whitemane", key="trialer-whitemane", member_id=member.id, source="claim"
        )
        session.add(character)
        await session.commit()
        member_id = member.id

    await _login_officer(member_client, discord_state, discord_id=7502)
    response = await member_client.post(
        "/api/epgp/imports",
        json={
            "payload": _export_string(
                _base_payload(
                    recruits=[
                        {
                            "id": "rec-trial",
                            "character": "Trialer-Whitemane",
                            "status": "trial",
                            "at": EXPORTED_AT,
                        }
                    ]
                )
            )
        },
    )
    assert response.status_code == 200, response.text

    async with db_sessionmaker() as session:
        refreshed = await session.get(Member, member_id)
        assert refreshed is not None
        assert refreshed.raid_status == "trial"
        assert refreshed.trial_started_at is not None


# --- member notes: upsert, voiding is one-way ------------------------------------------------------------------


async def test_member_notes_import_voids_and_cannot_be_unvoided(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7601)
    note_row = {
        "id": "note-1",
        "character": "Healer-Whitemane",
        "note": "Prefers healing",
        "officer": RECORDER,
        "at": EXPORTED_AT,
        "voided": False,
    }
    first = await member_client.post(
        "/api/epgp/imports", json={"payload": _export_string(_base_payload(member_notes=[note_row]))}
    )
    assert first.status_code == 200, first.text
    assert first.json()["member_notes"]["new"] == 1

    voided_row = dict(note_row)
    voided_row["voided"] = True
    second = await member_client.post(
        "/api/epgp/imports", json={"payload": _export_string(_base_payload(member_notes=[voided_row]))}
    )
    assert second.status_code == 200, second.text
    assert second.json()["member_notes"]["voided"] == 1

    # A re-import after voiding must never un-void it.
    unvoid_attempt = dict(note_row)
    unvoid_attempt["voided"] = False
    third = await member_client.post(
        "/api/epgp/imports", json={"payload": _export_string(_base_payload(member_notes=[unvoid_attempt]))}
    )
    assert third.status_code == 200, third.text
    assert third.json()["member_notes"]["new"] == 0
    assert third.json()["member_notes"]["updated"] == 0
    assert third.json()["member_notes"]["voided"] == 0

    async with db_sessionmaker() as session:
        row = (await session.execute(select(MemberNote).where(MemberNote.external_id == "note-1"))).scalar_one()
        assert row.voided_at is not None

    notes_list = await member_client.get("/api/epgp/member-notes/")
    assert notes_list.status_code == 200, notes_list.text
    assert notes_list.json()["notes"][0]["voided"] is True


# --- game-import v2 shape -------------------------------------------------------------------------------------------


async def test_game_import_v2_shape_decodes_and_officer_part_present(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7701)
    response = await member_client.get("/api/epgp/game-import")
    assert response.status_code == 200, response.text
    payload_string = response.json()["payload"]
    decoded = json.loads(base64.b64decode(payload_string.removeprefix("SQI1:")))
    assert decoded["v"] == 2
    for key in ("members", "news", "sheets", "crafters", "recipe_names", "officer"):
        assert key in decoded
    assert set(decoded["officer"]) == {"recruits", "member_notes", "inactive"}


async def test_game_import_requires_officer(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=7702, roles=[])
    response = await member_client.get("/api/epgp/game-import")
    assert response.status_code == 403


# --- roster endpoint: alts grouped under their main ----------------------------------------------------------------


async def test_guild_roster_endpoint_groups_alts_under_their_linked_member(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=7801, username="mainandalt", is_guild_member=True)
        session.add(member)
        await session.flush()
        main_char = WowCharacter(
            name="Main", realm="Whitemane", key="main-whitemane", member_id=member.id, is_main=True, source="claim"
        )
        alt_char = WowCharacter(
            name="Alt", realm="Whitemane", key="alt-whitemane", member_id=member.id, is_main=False, source="claim"
        )
        session.add_all([main_char, alt_char])
        await session.flush()
        now = datetime.now(UTC)
        session.add_all(
            [
                GuildRosterSnapshot(
                    character_id=main_char.id,
                    rank="Officer",
                    rank_index=1,
                    level=60,
                    zone="Orgrimmar",
                    last_seen_at=now,
                ),
                GuildRosterSnapshot(
                    character_id=alt_char.id, rank="Officer", rank_index=1, level=40, zone="Orgrimmar", last_seen_at=now
                ),
            ]
        )
        await session.commit()

    await login_as(member_client, discord_state, discord_id=7802, roles=[])
    response = await member_client.get("/api/guild/roster")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["members"]) == 1
    row = body["members"][0]
    assert row["main"] == "main-whitemane"
    assert {c["name"] for c in row["characters"]} == {"main-whitemane", "alt-whitemane"}
    assert body["unlinked"] == []


# --- enum validation: bad recruit status/vote/bank kind are rejected -----------------------------------------------


async def test_import_rejects_unknown_recruit_status(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=7901)
    bad_recruit = {
        "id": "rec-bad",
        "character": "Hopeful-Whitemane",
        "status": "banned",
        "at": EXPORTED_AT,
    }
    response = await member_client.post(
        "/api/epgp/imports", json={"payload": _export_string(_base_payload(recruits=[bad_recruit]))}
    )
    assert response.status_code == 400, response.text


async def test_import_rejects_unknown_recruit_vote(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=7902)
    bad_recruit = {
        "id": "rec-bad-vote",
        "character": "Hopeful-Whitemane",
        "status": "applicant",
        "votes": [{"officer": "Officer1-Whitemane", "vote": "maybe", "at": EXPORTED_AT}],
        "at": EXPORTED_AT,
    }
    response = await member_client.post(
        "/api/epgp/imports", json={"payload": _export_string(_base_payload(recruits=[bad_recruit]))}
    )
    assert response.status_code == 400, response.text


async def test_import_rejects_unknown_bank_kind(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=7903)
    bad_row = {
        "id": "bank-bad",
        "at": EXPORTED_AT,
        "character": "Banker-Whitemane",
        "kind": "teleport",
        "count": 1,
    }
    response = await member_client.post(
        "/api/epgp/imports", json={"payload": _export_string(_base_payload(bank=[bad_row]))}
    )
    assert response.status_code == 400, response.text


async def test_update_recruit_rejects_unknown_status(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=7904)
    import_response = await member_client.post(
        "/api/epgp/imports",
        json={
            "payload": _export_string(
                _base_payload(
                    recruits=[
                        {
                            "id": "rec-http",
                            "character": "Hopeful-Whitemane",
                            "status": "applicant",
                            "at": EXPORTED_AT,
                        }
                    ]
                )
            )
        },
    )
    assert import_response.status_code == 200, import_response.text
    recruits_list = await member_client.get("/api/epgp/recruits/")
    recruit_id = recruits_list.json()["recruits"][0]["id"]

    response = await member_client.put(f"/api/epgp/recruits/{recruit_id}", json={"status": "banned"})
    assert response.status_code == 400, response.text


async def test_add_recruit_vote_rejects_unknown_vote(member_client: AsyncTestClient, discord_state: dict) -> None:
    await _login_officer(member_client, discord_state, discord_id=7905)
    import_response = await member_client.post(
        "/api/epgp/imports",
        json={
            "payload": _export_string(
                _base_payload(
                    recruits=[
                        {
                            "id": "rec-http-vote",
                            "character": "Hopeful-Whitemane",
                            "status": "applicant",
                            "at": EXPORTED_AT,
                        }
                    ]
                )
            )
        },
    )
    assert import_response.status_code == 200, import_response.text
    recruits_list = await member_client.get("/api/epgp/recruits/")
    recruit_id = recruits_list.json()["recruits"][0]["id"]

    response = await member_client.post(f"/api/epgp/recruits/{recruit_id}/votes", json={"vote": "maybe"})
    assert response.status_code == 400, response.text


# --- real addon fixture: the game's uppercase class tokens and Lua's absent (not null) keys ---------------------


async def test_real_addon_v2_fixture_imports_every_section_and_is_idempotent(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raw_text = (FIXTURES_DIR / "export_v2.txt").read_text()
    payload = json.loads(base64.b64decode(raw_text.strip().removeprefix("SQX1:")))
    roster_members = (payload.get("roster") or {}).get("members", [])
    assert roster_members, "the fixture must carry a roster"
    await _login_officer(member_client, discord_state, discord_id=6801)

    first = await member_client.post("/api/epgp/imports", json={"payload": raw_text})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["roster"]["updated"] == len(roster_members)
    assert body["professions"]["updated"] == len(payload.get("professions", []))
    assert body["announcements"]["new"] == len(payload.get("announcements", []))
    assert body["bank"]["new"] == len(payload.get("bank", []))

    async with db_sessionmaker() as session:
        first_member = roster_members[0]
        character = (
            await session.execute(select(WowCharacter).where(WowCharacter.key == first_member["character"].lower()))
        ).scalar_one()
    assert character.wow_class == first_member["class"].lower()

    second = await member_client.post("/api/epgp/imports", json={"payload": raw_text})
    assert second.status_code == 200, second.text
    assert second.json()["announcements"]["new"] == 0
    assert second.json()["bank"]["new"] == 0
