"""Group voice channels (LFG): bot session lifecycle, officer stats/session browsing, and the public leaderboard."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import GroupSession, GroupSessionMember, GroupSessionPair, GroupSessionTranscript, Member
from tests.conftest import GUILD_ID
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

GROUPS_PATH = f"/api/guilds/{GUILD_ID}/groups"
NOW = datetime.now(UTC)


async def _seed_session(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    discord_channel_id: int,
    kind: str = "dungeon",
    name: str | None = None,
    channel_name: str = "dungeon-1",
    creator_discord_id: int = 1,
    owner_discord_id: int | None = None,
    started_at: datetime = NOW,
    ended_at: datetime | None = None,
    end_reason: str | None = None,
    peak_size: int = 0,
    grouped_minutes: int = 0,
) -> str:
    async with db_sessionmaker() as session:
        row = GroupSession(
            discord_channel_id=discord_channel_id,
            channel_name=channel_name,
            kind=kind,
            name=name,
            note=None,
            needs=[],
            cap=None,
            creator_discord_id=creator_discord_id,
            owner_discord_id=owner_discord_id if owner_discord_id is not None else creator_discord_id,
            event_id=None,
            card_message_id=None,
            started_at=started_at,
            ended_at=ended_at,
            end_reason=end_reason,
            peak_size=peak_size,
            grouped_minutes=grouped_minutes,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return str(row.id)


async def _seed_member_minutes(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    discord_id: int,
    display_name: str = "Someone",
    minutes: int = 0,
) -> None:
    async with db_sessionmaker() as session:
        session.add(
            GroupSessionMember(session_id=session_id, discord_id=discord_id, display_name=display_name, minutes=minutes)
        )
        await session.commit()


async def _seed_pair_minutes(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    discord_id_a: int,
    discord_id_b: int,
    minutes: int,
) -> None:
    async with db_sessionmaker() as session:
        session.add(
            GroupSessionPair(
                session_id=session_id, discord_id_a=discord_id_a, discord_id_b=discord_id_b, minutes=minutes
            )
        )
        await session.commit()


async def _seed_member(db_sessionmaker: async_sessionmaker[AsyncSession], *, discord_id: int, display_name: str) -> int:
    async with db_sessionmaker() as session:
        member = Member(discord_id=discord_id, username=display_name, is_guild_member=True)
        session.add(member)
        await session.commit()
        await session.refresh(member)
        return member.id


# --- bot: session lifecycle -----------------------------------------------------------------------------------


async def test_create_session_404s_for_non_site_guild(client: AsyncTestClient) -> None:
    response = await client.post(
        f"/api/guilds/{GUILD_ID + 1}/groups",
        json={"discord_channel_id": "100", "channel_name": "dungeon-1", "kind": "dungeon", "creator_discord_id": "1"},
    )
    assert response.status_code == 404


async def test_create_session_returns_schema(client: AsyncTestClient) -> None:
    response = await client.post(
        f"{GROUPS_PATH}",
        json={
            "discord_channel_id": "101",
            "channel_name": "dungeon-1",
            "kind": "dungeon",
            "creator_discord_id": "42",
            "needs": ["tank", "healer"],
            "cap": 5,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["discord_channel_id"] == "101"
    assert body["kind"] == "dungeon"
    assert body["creator_discord_id"] == "42"
    assert body["owner_discord_id"] == "42"
    assert body["needs"] == ["tank", "healer"]
    assert body["cap"] == 5
    assert body["ended_at"] is None
    assert body["members"] == []


async def test_create_session_duplicate_channel_is_409(client: AsyncTestClient) -> None:
    body = {"discord_channel_id": "102", "channel_name": "dungeon-2", "kind": "dungeon", "creator_discord_id": "1"}
    first = await client.post(f"{GROUPS_PATH}", json=body)
    second = await client.post(f"{GROUPS_PATH}", json=body)
    assert first.status_code == 201
    assert second.status_code == 409


async def test_get_session_404s_for_unknown_session(client: AsyncTestClient) -> None:
    response = await client.get(f"{GROUPS_PATH}/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_list_open_sessions_excludes_closed(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    open_id = await _seed_session(db_sessionmaker, discord_channel_id=201)
    await _seed_session(db_sessionmaker, discord_channel_id=202, ended_at=NOW, end_reason="owner")
    response = await client.get(f"{GROUPS_PATH}/open")
    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert ids == [open_id]


async def test_update_session_ignores_null_channel_name_but_applies_other_fields(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    session_id = await _seed_session(db_sessionmaker, discord_channel_id=203, channel_name="dungeon-3")
    response = await client.patch(
        f"{GROUPS_PATH}/{session_id}", json={"channel_name": None, "name": "Deadmines", "cap": 10}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["channel_name"] == "dungeon-3"  # never cleared
    assert body["name"] == "Deadmines"
    assert body["cap"] == 10

    renamed = await client.patch(f"{GROUPS_PATH}/{session_id}", json={"channel_name": "dungeon-deadmines"})
    assert renamed.json()["channel_name"] == "dungeon-deadmines"


async def test_presence_push_is_idempotent_and_tracks_the_max(client: AsyncTestClient) -> None:
    created = await client.post(
        f"{GROUPS_PATH}",
        json={"discord_channel_id": "204", "channel_name": "dungeon-4", "kind": "dungeon", "creator_discord_id": "1"},
    )
    session_id = created.json()["id"]
    report = {
        "peak_size": 2,
        "grouped_minutes": 15,
        "members": [
            {"discord_id": "1", "display_name": "Alice", "minutes": 15},
            {"discord_id": "2", "display_name": "Bob", "minutes": 15},
        ],
        "pairs": [{"discord_id_a": "1", "discord_id_b": "2", "minutes": 15}],
    }
    first = await client.put(f"{GROUPS_PATH}/{session_id}/presence", json=report)
    second = await client.put(f"{GROUPS_PATH}/{session_id}/presence", json=report)
    assert first.status_code == 204
    assert second.status_code == 204

    smaller = await client.put(
        f"{GROUPS_PATH}/{session_id}/presence",
        json={
            "peak_size": 1,
            "grouped_minutes": 1,
            "members": [{"discord_id": "1", "display_name": "Alice", "minutes": 1}],
            "pairs": [],
        },
    )
    assert smaller.status_code == 204

    fetched = await client.get(f"{GROUPS_PATH}/{session_id}")
    body = fetched.json()
    assert body["peak_size"] == 2  # never lowered
    assert body["grouped_minutes"] == 15
    members_by_id = {m["discord_id"]: m["minutes"] for m in body["members"]}
    assert members_by_id == {"1": 15, "2": 15}
    assert body["pairs"] == [{"discord_id_a": "1", "discord_id_b": "2", "minutes": 15}]


async def test_close_session_sets_ended_at_and_stores_transcript(client: AsyncTestClient) -> None:
    created = await client.post(
        f"{GROUPS_PATH}",
        json={"discord_channel_id": "205", "channel_name": "dungeon-5", "kind": "dungeon", "creator_discord_id": "1"},
    )
    session_id = created.json()["id"]
    close_body = {
        "end_reason": "owner",
        "presence": {"peak_size": 2, "grouped_minutes": 20, "members": [], "pairs": []},
        "transcript": [
            {
                "author_discord_id": "1",
                "author_name": "Alice",
                "content": "gg",
                "created_at": NOW.isoformat(),
                "attachments": [],
            }
        ],
    }
    response = await client.post(f"{GROUPS_PATH}/{session_id}/close", json=close_body)
    assert response.status_code == 204
    fetched = await client.get(f"{GROUPS_PATH}/{session_id}")
    body = fetched.json()
    assert body["ended_at"] is not None
    assert body["end_reason"] == "owner"
    assert body["peak_size"] == 2


async def test_close_session_is_idempotent_and_keeps_the_first_end_reason(client: AsyncTestClient) -> None:
    created = await client.post(
        f"{GROUPS_PATH}",
        json={"discord_channel_id": "206", "channel_name": "dungeon-6", "kind": "dungeon", "creator_discord_id": "1"},
    )
    session_id = created.json()["id"]
    await client.post(
        f"{GROUPS_PATH}/{session_id}/close",
        json={
            "end_reason": "owner",
            "presence": {"peak_size": 1, "grouped_minutes": 5, "members": [], "pairs": []},
            "transcript": [],
        },
    )
    second = await client.post(
        f"{GROUPS_PATH}/{session_id}/close",
        json={
            "end_reason": "empty",
            "presence": {"peak_size": 3, "grouped_minutes": 30, "members": [], "pairs": []},
            "transcript": [],
        },
    )
    assert second.status_code == 204
    fetched = await client.get(f"{GROUPS_PATH}/{session_id}")
    body = fetched.json()
    assert body["end_reason"] == "owner"  # kept the first close's reason
    assert body["peak_size"] == 3  # presence still merges
    assert body["grouped_minutes"] == 30


async def test_purge_deletes_transcripts_past_retention(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    old_session_id = await _seed_session(
        db_sessionmaker, discord_channel_id=207, ended_at=NOW - timedelta(days=31), end_reason="owner"
    )
    recent_session_id = await _seed_session(
        db_sessionmaker, discord_channel_id=208, ended_at=NOW - timedelta(days=1), end_reason="owner"
    )
    async with db_sessionmaker() as session:
        session.add(GroupSessionTranscript(session_id=old_session_id, messages=[]))
        session.add(GroupSessionTranscript(session_id=recent_session_id, messages=[]))
        await session.commit()

    response = await client.post(f"{GROUPS_PATH}/purge")
    assert response.status_code == 200
    assert response.json()["deleted"] == 1

    async with db_sessionmaker() as session:
        remaining = (await session.execute(select(GroupSessionTranscript.session_id))).scalars().all()
    assert [str(session_id) for session_id in remaining] == [recent_session_id]


# --- officer: stats and session browsing -----------------------------------------------------------------------


async def test_stats_requires_officer(member_client: AsyncTestClient, discord_state: dict) -> None:
    response = await member_client.get("/api/groups/stats")
    assert response.status_code == 401
    await login_as(member_client, discord_state, discord_id=900, roles=[])
    forbidden = await member_client.get("/api/groups/stats")
    assert forbidden.status_code == 403


async def test_stats_only_counts_sessions_meeting_the_threshold(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    # Counted: peak_size >= 2 and grouped_minutes >= 10, two members with 10+ minutes each, a named instance.
    counted_id = await _seed_session(
        db_sessionmaker,
        discord_channel_id=301,
        kind="dungeon",
        name="Deadmines",
        creator_discord_id=1001,
        peak_size=2,
        grouped_minutes=12,
    )
    await _seed_member_minutes(
        db_sessionmaker, session_id=counted_id, discord_id=1001, display_name="Alice", minutes=12
    )
    await _seed_member_minutes(db_sessionmaker, session_id=counted_id, discord_id=1002, display_name="Bob", minutes=12)
    await _seed_pair_minutes(db_sessionmaker, session_id=counted_id, discord_id_a=1001, discord_id_b=1002, minutes=12)

    # Not counted: only one member ever showed up (peak_size 1).
    uncounted_id = await _seed_session(
        db_sessionmaker, discord_channel_id=302, creator_discord_id=1001, peak_size=1, grouped_minutes=5
    )
    await _seed_member_minutes(
        db_sessionmaker, session_id=uncounted_id, discord_id=1001, display_name="Alice", minutes=5
    )

    await login_as(member_client, discord_state, discord_id=901, roles=[OFFICER_ROLE_ID])
    response = await member_client.get("/api/groups/stats")
    assert response.status_code == 200
    stats = response.json()

    assert stats["sessions_total"] == 2
    assert stats["sessions_counted"] == 1
    assert stats["grouped_minutes"] == 12

    by_kind = {row["kind"]: row for row in stats["by_kind"]}
    assert by_kind["dungeon"]["sessions"] == 1
    assert by_kind["dungeon"]["minutes"] == 24  # Alice 12 + Bob 12, from the counted session only

    assert stats["top_instances"] == [{"kind": "dungeon", "name": "Deadmines", "sessions": 1}]

    most_grouped = {row["person"]["discord_id"]: row for row in stats["most_grouped"]}
    assert most_grouped["1001"]["value"] == 12  # only the counted session's minutes count
    assert most_grouped["1001"]["sessions"] == 1
    assert most_grouped["1002"]["value"] == 12

    most_social = {row["person"]["discord_id"]: row for row in stats["most_social"]}
    assert most_social["1001"]["value"] == 1  # one distinct partner
    assert most_social["1002"]["value"] == 1

    assert len(stats["best_duos"]) == 1
    assert stats["best_duos"][0]["minutes"] == 12

    most_led = {row["person"]["discord_id"]: row for row in stats["most_led"]}
    assert most_led["1001"]["value"] == 1  # only the counted session they created


async def test_list_sessions_respects_limit_and_before(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    older_id = await _seed_session(db_sessionmaker, discord_channel_id=401, started_at=NOW - timedelta(hours=2))
    newer_id = await _seed_session(db_sessionmaker, discord_channel_id=402, started_at=NOW - timedelta(hours=1))
    await login_as(member_client, discord_state, discord_id=902, roles=[OFFICER_ROLE_ID])

    all_sessions = await member_client.get("/api/groups/sessions")
    assert [row["id"] for row in all_sessions.json()] == [newer_id, older_id]

    limited = await member_client.get("/api/groups/sessions", params={"limit": 1})
    assert [row["id"] for row in limited.json()] == [newer_id]

    before = await member_client.get(
        "/api/groups/sessions", params={"before": (NOW - timedelta(minutes=30)).isoformat()}
    )
    assert [row["id"] for row in before.json()] == [newer_id, older_id]


async def test_session_detail_has_transcript_when_within_retention(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    session_id = await _seed_session(
        db_sessionmaker,
        discord_channel_id=403,
        ended_at=NOW - timedelta(days=5),
        end_reason="owner",
        peak_size=2,
        grouped_minutes=12,
    )
    async with db_sessionmaker() as session:
        session.add(
            GroupSessionTranscript(
                session_id=session_id,
                messages=[
                    {
                        "author_discord_id": "1",
                        "author_name": "Alice",
                        "content": "hi",
                        "created_at": NOW.isoformat(),
                        "attachments": [],
                    }
                ],
            )
        )
        await session.commit()
    await login_as(member_client, discord_state, discord_id=903, roles=[OFFICER_ROLE_ID])
    response = await member_client.get(f"/api/groups/sessions/{session_id}")
    assert response.status_code == 200
    body = response.json()
    assert len(body["transcript"]) == 1
    message = body["transcript"][0]
    assert (message["author_discord_id"], message["author_name"], message["content"], message["attachments"]) == (
        "1",
        "Alice",
        "hi",
        [],
    )
    assert datetime.fromisoformat(message["created_at"]) == NOW
    assert body["transcript_expires_at"] is not None


async def test_session_detail_transcript_is_null_once_purged(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    session_id = await _seed_session(
        db_sessionmaker, discord_channel_id=404, ended_at=NOW - timedelta(days=40), end_reason="owner"
    )
    await login_as(member_client, discord_state, discord_id=904, roles=[OFFICER_ROLE_ID])
    response = await member_client.get(f"/api/groups/sessions/{session_id}")
    assert response.status_code == 200
    assert response.json()["transcript"] is None


async def test_session_detail_404s_for_unknown_session(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=905, roles=[OFFICER_ROLE_ID])
    response = await member_client.get("/api/groups/sessions/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# --- public: leaderboard -----------------------------------------------------------------------------------


async def test_leaderboard_only_includes_members_with_a_site_account(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    linked_id = await _seed_member(db_sessionmaker, discord_id=5001, display_name="Linked")
    session_id = await _seed_session(db_sessionmaker, discord_channel_id=501, peak_size=2, grouped_minutes=15)
    await _seed_member_minutes(
        db_sessionmaker, session_id=session_id, discord_id=5001, display_name="Linked", minutes=15
    )
    await _seed_member_minutes(
        db_sessionmaker, session_id=session_id, discord_id=5002, display_name="Unlinked", minutes=15
    )

    response = await client.get("/api/groups/leaderboard")
    assert response.status_code == 200
    body = response.json()
    month_ids = {row["member_id"] for row in body["month"]}
    assert month_ids == {linked_id}
    assert body["month"][0]["minutes"] == 15
    assert body["month"][0]["groups"] == 1


async def test_leaderboard_all_time_includes_sessions_outside_the_30_day_window(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    linked_id = await _seed_member(db_sessionmaker, discord_id=5003, display_name="OldTimer")
    session_id = await _seed_session(
        db_sessionmaker, discord_channel_id=502, started_at=NOW - timedelta(days=60), peak_size=2, grouped_minutes=15
    )
    await _seed_member_minutes(
        db_sessionmaker, session_id=session_id, discord_id=5003, display_name="OldTimer", minutes=15
    )
    await _seed_member_minutes(
        db_sessionmaker, session_id=session_id, discord_id=5004, display_name="Other", minutes=15
    )

    response = await client.get("/api/groups/leaderboard")
    assert response.status_code == 200
    body = response.json()
    assert body["month"] == []  # outside the last 30 days
    assert {row["member_id"] for row in body["all_time"]} == {linked_id}


# --- badges: party_animal / party_leader -----------------------------------------------------------------------


async def test_party_animal_awarded_at_threshold(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=6001, display_name="Partier")
    for channel_id in range(600, 650):  # 50 counted sessions, Partier in each for 10+ minutes
        session_id = await _seed_session(
            db_sessionmaker, discord_channel_id=channel_id, peak_size=2, grouped_minutes=10
        )
        await _seed_member_minutes(
            db_sessionmaker, session_id=session_id, discord_id=6001, display_name="Partier", minutes=10
        )
        await _seed_member_minutes(
            db_sessionmaker, session_id=session_id, discord_id=6002, display_name="Other", minutes=10
        )
    response = await client.get(f"{GROUPS_PATH.replace('/groups', '')}/badges/sync")
    assert response.status_code == 200
    role_state = {row["discord_id"]: row["badge_ids"] for row in response.json()["role_state"]}
    assert "party_animal" in role_state[6001]


async def test_party_animal_not_awarded_below_threshold(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=6101, display_name="Casual")
    for channel_id in range(700, 720):  # only 20 counted sessions, below the 50 threshold
        session_id = await _seed_session(
            db_sessionmaker, discord_channel_id=channel_id, peak_size=2, grouped_minutes=10
        )
        await _seed_member_minutes(
            db_sessionmaker, session_id=session_id, discord_id=6101, display_name="Casual", minutes=10
        )
        await _seed_member_minutes(
            db_sessionmaker, session_id=session_id, discord_id=6102, display_name="Other", minutes=10
        )
    response = await client.get(f"{GROUPS_PATH.replace('/groups', '')}/badges/sync")
    assert response.status_code == 200
    role_state = {row["discord_id"]: row["badge_ids"] for row in response.json()["role_state"]}
    assert "party_animal" not in role_state.get(6101, [])


async def test_party_leader_awarded_at_threshold(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=6201, display_name="Leader")
    for channel_id in range(800, 825):  # 25 counted sessions created by Leader
        session_id = await _seed_session(
            db_sessionmaker, discord_channel_id=channel_id, creator_discord_id=6201, peak_size=2, grouped_minutes=10
        )
        await _seed_member_minutes(
            db_sessionmaker, session_id=session_id, discord_id=6201, display_name="Leader", minutes=10
        )
        await _seed_member_minutes(
            db_sessionmaker, session_id=session_id, discord_id=6202, display_name="Other", minutes=10
        )
    response = await client.get(f"{GROUPS_PATH.replace('/groups', '')}/badges/sync")
    assert response.status_code == 200
    role_state = {row["discord_id"]: row["badge_ids"] for row in response.json()["role_state"]}
    assert "party_leader" in role_state[6201]
