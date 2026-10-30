"""Attendance: the ``attended``/no-show SQL conditions, officer marking, bot voice push, and the GM report/trends."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_api.lib.attendance import attended_condition, no_show_condition
from sidequest_bot.api_client import API_KEY_HEADER
from sidequest_common.models import EventSignup, EventVoicePresence, GuildEvent, Member
from tests.conftest import GUILD_ID, TEST_API_KEY
from tests.unit.api.conftest import GM_ROLE_ID, OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PAST = datetime.now(UTC) - timedelta(hours=2)
FUTURE = datetime.now(UTC) + timedelta(hours=2)


async def _seed_event(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    title: str = "Molten Core",
    kind: str = "raid",
    starts_at: datetime = PAST,
    status: str = "scheduled",
    attendance_taken_at: datetime | None = None,
) -> str:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind=kind,
            title=title,
            location="Molten Core",
            starts_at=starts_at,
            status=status,
            notes=None,
            attendance_taken_at=attendance_taken_at,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return str(event.id)


async def _seed_member(
    db_sessionmaker: async_sessionmaker[AsyncSession], *, discord_id: int, display_name: str = "Thrall"
) -> int:
    async with db_sessionmaker() as session:
        member = Member(discord_id=discord_id, username=display_name, is_guild_member=True)
        session.add(member)
        await session.commit()
        await session.refresh(member)
        return member.id


async def _seed_signup(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    event_id: str,
    member_id: int,
    status: str = "signed",
    attended: bool | None = None,
    is_walk_in: bool = False,
) -> str:
    async with db_sessionmaker() as session:
        signup = EventSignup(
            event_id=event_id, member_id=member_id, status=status, attended=attended, is_walk_in=is_walk_in
        )
        session.add(signup)
        await session.commit()
        await session.refresh(signup)
        return str(signup.id)


# --- attended_condition / no_show_condition ----------------------------------------------------------------------


async def _came(db_sessionmaker: async_sessionmaker[AsyncSession], signup_id: str) -> bool:
    async with db_sessionmaker() as session:
        statement = (
            select(attended_condition())
            .select_from(EventSignup)
            .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
            .where(EventSignup.id == signup_id)
        )
        return bool((await session.execute(statement)).scalar_one())


async def _no_show(db_sessionmaker: async_sessionmaker[AsyncSession], signup_id: str) -> bool:
    async with db_sessionmaker() as session:
        statement = (
            select(no_show_condition())
            .select_from(EventSignup)
            .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
            .where(EventSignup.id == signup_id)
        )
        return bool((await session.execute(statement)).scalar_one())


async def test_untaken_past_event_signed_signup_counts_as_attended(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    member_id = await _seed_member(db_sessionmaker, discord_id=1)
    signup_id = await _seed_signup(db_sessionmaker, event_id=event_id, member_id=member_id, status="signed")
    assert await _came(db_sessionmaker, signup_id) is True
    assert await _no_show(db_sessionmaker, signup_id) is False


async def test_untaken_past_event_tentative_signup_does_not_count(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    member_id = await _seed_member(db_sessionmaker, discord_id=1)
    signup_id = await _seed_signup(db_sessionmaker, event_id=event_id, member_id=member_id, status="tentative")
    assert await _came(db_sessionmaker, signup_id) is False
    assert await _no_show(db_sessionmaker, signup_id) is False


async def test_future_event_never_counts_as_attended_even_if_signed(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    event_id = await _seed_event(db_sessionmaker, starts_at=FUTURE)
    member_id = await _seed_member(db_sessionmaker, discord_id=1)
    signup_id = await _seed_signup(db_sessionmaker, event_id=event_id, member_id=member_id, status="signed")
    assert await _came(db_sessionmaker, signup_id) is False


async def test_cancelled_event_never_counts_as_attended(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    event_id = await _seed_event(db_sessionmaker, status="cancelled")
    member_id = await _seed_member(db_sessionmaker, discord_id=1)
    signup_id = await _seed_signup(db_sessionmaker, event_id=event_id, member_id=member_id, status="signed")
    assert await _came(db_sessionmaker, signup_id) is False


async def test_taken_event_requires_explicit_attended_true(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    event_id = await _seed_event(db_sessionmaker, attendance_taken_at=datetime.now(UTC))
    member_id = await _seed_member(db_sessionmaker, discord_id=1)
    signed_but_unmarked = await _seed_signup(db_sessionmaker, event_id=event_id, member_id=member_id, status="signed")
    assert await _came(db_sessionmaker, signed_but_unmarked) is False


async def test_taken_event_marked_attended_counts(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    event_id = await _seed_event(db_sessionmaker, attendance_taken_at=datetime.now(UTC))
    member_id = await _seed_member(db_sessionmaker, discord_id=1)
    signup_id = await _seed_signup(
        db_sessionmaker, event_id=event_id, member_id=member_id, status="signed", attended=True
    )
    assert await _came(db_sessionmaker, signup_id) is True
    assert await _no_show(db_sessionmaker, signup_id) is False


async def test_taken_event_marked_not_attended_is_no_show(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    event_id = await _seed_event(db_sessionmaker, attendance_taken_at=datetime.now(UTC))
    member_id = await _seed_member(db_sessionmaker, discord_id=1)
    signup_id = await _seed_signup(
        db_sessionmaker, event_id=event_id, member_id=member_id, status="signed", attended=False
    )
    assert await _came(db_sessionmaker, signup_id) is False
    assert await _no_show(db_sessionmaker, signup_id) is True


async def test_taken_event_tentative_marked_false_is_not_a_no_show(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Only a ``signed`` sign-up can be a no-show: tentative/absent members weren't committed to coming."""
    event_id = await _seed_event(db_sessionmaker, attendance_taken_at=datetime.now(UTC))
    member_id = await _seed_member(db_sessionmaker, discord_id=1)
    signup_id = await _seed_signup(
        db_sessionmaker, event_id=event_id, member_id=member_id, status="tentative", attended=False
    )
    assert await _no_show(db_sessionmaker, signup_id) is False


# --- officer marking screen ----------------------------------------------------------------------------------


async def test_non_officer_gets_403_on_attendance_list(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=10, roles=[])
    response = await member_client.get("/api/attendance/events")
    assert response.status_code == 403


async def test_officer_sees_needs_attendance_marker(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    past_id = await _seed_event(db_sessionmaker, title="Past raid")
    future_id = await _seed_event(db_sessionmaker, title="Future raid", starts_at=FUTURE)
    taken_id = await _seed_event(db_sessionmaker, title="Already taken", attendance_taken_at=datetime.now(UTC))
    await login_as(member_client, discord_state, discord_id=11, roles=[OFFICER_ROLE_ID])
    response = await member_client.get("/api/attendance/events")
    assert response.status_code == 200
    by_id = {row["id"]: row for row in response.json()}
    assert by_id[past_id]["needs_attendance"] is True
    assert taken_id not in {row["id"] for row in response.json()} or by_id[taken_id]["needs_attendance"] is False
    assert future_id not in by_id


async def test_attendance_detail_includes_voice_minutes_and_suggestion(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="social")
    member_id = await _seed_member(db_sessionmaker, discord_id=2001, display_name="Jaina")
    tentative_id = await _seed_member(db_sessionmaker, discord_id=2002, display_name="Thrall")
    await _seed_signup(db_sessionmaker, event_id=event_id, member_id=member_id, status="signed")
    await _seed_signup(db_sessionmaker, event_id=event_id, member_id=tentative_id, status="tentative")
    await login_as(member_client, discord_state, discord_id=20, roles=[OFFICER_ROLE_ID])
    voice_response = await member_client.put(
        f"/api/guilds/{GUILD_ID}/attendance/voice",
        json={"event_id": event_id, "entries": [{"discord_id": "2002", "minutes": 45}]},
        headers={API_KEY_HEADER: TEST_API_KEY},
    )
    assert voice_response.status_code == 204
    detail = await member_client.get(f"/api/events/{event_id}/attendance")
    assert detail.status_code == 200
    rows = {row["member_id"]: row for row in detail.json()["signups"]}
    assert rows[member_id]["suggested_attended"] is True  # signed
    assert rows[tentative_id]["suggested_attended"] is True  # tentative but >=30 min in voice
    assert rows[tentative_id]["voice_minutes"] == 45


async def test_mark_attendance_sets_taken_at_and_audits(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    came_id = await _seed_member(db_sessionmaker, discord_id=3001, display_name="Came")
    no_show_id = await _seed_member(db_sessionmaker, discord_id=3002, display_name="NoShow")
    came_signup = await _seed_signup(db_sessionmaker, event_id=event_id, member_id=came_id, status="signed")
    no_show_signup = await _seed_signup(db_sessionmaker, event_id=event_id, member_id=no_show_id, status="signed")
    await login_as(member_client, discord_state, discord_id=30, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(
        f"/api/events/{event_id}/attendance",
        json={
            "entries": [
                {"signup_id": came_signup, "attended": True},
                {"signup_id": no_show_signup, "attended": False},
            ],
            "walk_ins": [],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["event"]["attendance_taken_at"] is not None
    assert body["event"]["needs_attendance"] is False
    log = await member_client.get("/api/gm/log?kind=officer")
    # non-GM can't read the log; just confirm the mark endpoint itself succeeded with the right counts
    assert log.status_code == 403
    assert {(row["member_id"], row["attended"]) for row in body["signups"]} == {(came_id, True), (no_show_id, False)}


async def test_mark_attendance_before_event_starts_is_409(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, starts_at=FUTURE)
    await login_as(member_client, discord_state, discord_id=31, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(f"/api/events/{event_id}/attendance", json={"entries": [], "walk_ins": []})
    assert response.status_code == 409


async def test_mark_attendance_on_cancelled_event_is_409(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, status="cancelled")
    await login_as(member_client, discord_state, discord_id=32, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(f"/api/events/{event_id}/attendance", json={"entries": [], "walk_ins": []})
    assert response.status_code == 409


async def test_walk_in_creates_signed_attended_signup(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="social")
    walk_in_member_id = await _seed_member(db_sessionmaker, discord_id=4001, display_name="Walker")
    await login_as(member_client, discord_state, discord_id=40, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(
        f"/api/events/{event_id}/attendance",
        json={"entries": [], "walk_ins": [{"member_id": walk_in_member_id}]},
    )
    assert response.status_code == 200
    rows = {row["member_id"]: row for row in response.json()["signups"]}
    assert rows[walk_in_member_id]["status"] == "signed"
    assert rows[walk_in_member_id]["attended"] is True
    assert rows[walk_in_member_id]["is_walk_in"] is True


async def test_walk_in_on_raid_without_character_class_role_is_400(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="raid")
    walk_in_member_id = await _seed_member(db_sessionmaker, discord_id=4002, display_name="Walker")
    await login_as(member_client, discord_state, discord_id=41, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(
        f"/api/events/{event_id}/attendance",
        json={"entries": [], "walk_ins": [{"member_id": walk_in_member_id}]},
    )
    assert response.status_code == 400


async def test_walk_in_duplicating_existing_signup_is_409(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="social")
    member_id = await _seed_member(db_sessionmaker, discord_id=4003, display_name="AlreadyIn")
    await _seed_signup(db_sessionmaker, event_id=event_id, member_id=member_id, status="signed")
    await login_as(member_client, discord_state, discord_id=42, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(
        f"/api/events/{event_id}/attendance",
        json={"entries": [], "walk_ins": [{"member_id": member_id}]},
    )
    assert response.status_code == 409


# --- bot voice presence push ---------------------------------------------------------------------------------


async def test_voice_presence_push_is_idempotent(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    body = {"event_id": event_id, "entries": [{"discord_id": "5001", "minutes": 12}]}
    first = await member_client.put(
        f"/api/guilds/{GUILD_ID}/attendance/voice", json=body, headers={API_KEY_HEADER: TEST_API_KEY}
    )
    second = await member_client.put(
        f"/api/guilds/{GUILD_ID}/attendance/voice", json=body, headers={API_KEY_HEADER: TEST_API_KEY}
    )
    assert first.status_code == 204
    assert second.status_code == 204
    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(EventVoicePresence).where(EventVoicePresence.event_id == event_id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].minutes == 12


async def test_voice_presence_push_tracks_the_highest_reported_total(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await member_client.put(
        f"/api/guilds/{GUILD_ID}/attendance/voice",
        json={"event_id": event_id, "entries": [{"discord_id": "5002", "minutes": 10}]},
        headers={API_KEY_HEADER: TEST_API_KEY},
    )
    await member_client.put(
        f"/api/guilds/{GUILD_ID}/attendance/voice",
        json={"event_id": event_id, "entries": [{"discord_id": "5002", "minutes": 25}]},
        headers={API_KEY_HEADER: TEST_API_KEY},
    )
    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(EventVoicePresence).where(EventVoicePresence.event_id == event_id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].minutes == 25


async def test_voice_presence_push_never_lowers_a_stored_total(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A worker restart resets its in-memory counter to 0; a smaller report must not erase accumulated minutes."""
    event_id = await _seed_event(db_sessionmaker)
    await member_client.put(
        f"/api/guilds/{GUILD_ID}/attendance/voice",
        json={"event_id": event_id, "entries": [{"discord_id": "5002", "minutes": 90}]},
        headers={API_KEY_HEADER: TEST_API_KEY},
    )
    await member_client.put(
        f"/api/guilds/{GUILD_ID}/attendance/voice",
        json={"event_id": event_id, "entries": [{"discord_id": "5002", "minutes": 1}]},
        headers={API_KEY_HEADER: TEST_API_KEY},
    )
    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(EventVoicePresence).where(EventVoicePresence.event_id == event_id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].minutes == 90


async def test_voice_presence_push_404s_for_non_site_guild(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    response = await member_client.put(
        f"/api/guilds/{GUILD_ID + 1}/attendance/voice",
        json={"event_id": event_id, "entries": [{"discord_id": "1", "minutes": 1}]},
        headers={API_KEY_HEADER: TEST_API_KEY},
    )
    assert response.status_code == 404


async def test_get_voice_presence_returns_stored_totals_for_resume(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await member_client.put(
        f"/api/guilds/{GUILD_ID}/attendance/voice",
        json={"event_id": event_id, "entries": [{"discord_id": "5002", "minutes": 42}]},
        headers={API_KEY_HEADER: TEST_API_KEY},
    )
    response = await member_client.get(
        f"/api/guilds/{GUILD_ID}/attendance/voice/{event_id}", headers={API_KEY_HEADER: TEST_API_KEY}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == event_id
    assert body["entries"] == [{"discord_id": "5002", "minutes": 42}]


async def test_get_voice_presence_404s_for_non_site_guild(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    response = await member_client.get(
        f"/api/guilds/{GUILD_ID + 1}/attendance/voice/{event_id}", headers={API_KEY_HEADER: TEST_API_KEY}
    )
    assert response.status_code == 404


# --- GM report and trends -------------------------------------------------------------------------------------


async def test_report_is_gm_only(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=50, roles=[OFFICER_ROLE_ID])
    response = await member_client.get("/api/attendance/report")
    assert response.status_code == 403


async def test_report_counts_signed_up_came_no_shows_and_walk_ins(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, attendance_taken_at=datetime.now(UTC))
    member_id = await _seed_member(db_sessionmaker, discord_id=6001, display_name="Reporter")
    await _seed_signup(db_sessionmaker, event_id=event_id, member_id=member_id, status="signed", attended=True)
    second_event = await _seed_event(db_sessionmaker, title="Second", attendance_taken_at=datetime.now(UTC))
    await _seed_signup(db_sessionmaker, event_id=second_event, member_id=member_id, status="signed", attended=False)
    walk_in_event = await _seed_event(db_sessionmaker, title="Walk-in night", attendance_taken_at=datetime.now(UTC))
    await _seed_signup(
        db_sessionmaker, event_id=walk_in_event, member_id=member_id, status="signed", attended=True, is_walk_in=True
    )
    await login_as(member_client, discord_state, discord_id=51, roles=[GM_ROLE_ID])
    response = await member_client.get("/api/attendance/report", params={"window": "all_time"})
    assert response.status_code == 200
    row = next(row for row in response.json()["rows"] if row["member_id"] == member_id)
    assert row["signed_up"] == 2
    assert row["came"] == 2  # the signed+attended signup, plus the walk-in (who also attended)
    assert row["no_shows"] == 1
    assert row["walk_ins"] == 1
    assert row["attendance_rate"] == 0.5  # 1 attended signed sign-up (not the walk-in) / 2 signed sign-ups
    assert row["last_attended"] is not None


async def test_report_walk_ins_do_not_push_rate_above_100_percent(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A member's one signed sign-up plus a separate walk-in attendance must not push the rate above 100%."""
    event_id = await _seed_event(db_sessionmaker, attendance_taken_at=datetime.now(UTC))
    member_id = await _seed_member(db_sessionmaker, discord_id=6004, display_name="Puggy")
    await _seed_signup(db_sessionmaker, event_id=event_id, member_id=member_id, status="signed", attended=True)
    walk_in_event = await _seed_event(db_sessionmaker, title="Pug night", attendance_taken_at=datetime.now(UTC))
    await _seed_signup(
        db_sessionmaker, event_id=walk_in_event, member_id=member_id, status="signed", attended=True, is_walk_in=True
    )
    await login_as(member_client, discord_state, discord_id=55, roles=[GM_ROLE_ID])
    response = await member_client.get("/api/attendance/report", params={"window": "all_time"})
    assert response.status_code == 200
    row = next(row for row in response.json()["rows"] if row["member_id"] == member_id)
    assert row["signed_up"] == 1
    assert row["came"] == 2  # the signed sign-up plus the walk-in, both attended
    assert row["attendance_rate"] == 1.0  # never above 1.0, even though `came` exceeds `signed_up`


async def test_report_last_30_excludes_older_events(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    old_event = await _seed_event(db_sessionmaker, starts_at=datetime.now(UTC) - timedelta(days=60))
    member_id = await _seed_member(db_sessionmaker, discord_id=6002, display_name="OldTimer")
    await _seed_signup(db_sessionmaker, event_id=old_event, member_id=member_id, status="signed")
    await login_as(member_client, discord_state, discord_id=52, roles=[GM_ROLE_ID])
    response = await member_client.get("/api/attendance/report", params={"window": "last_30"})
    assert response.status_code == 200
    assert not any(row["member_id"] == member_id for row in response.json()["rows"])


async def test_report_raids_only_filters_non_raid_kinds(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    social_event = await _seed_event(db_sessionmaker, kind="social")
    member_id = await _seed_member(db_sessionmaker, discord_id=6003, display_name="Socialite")
    await _seed_signup(db_sessionmaker, event_id=social_event, member_id=member_id, status="signed")
    await login_as(member_client, discord_state, discord_id=53, roles=[GM_ROLE_ID])
    response = await member_client.get("/api/attendance/report", params={"window": "all_time", "raids_only": "true"})
    assert response.status_code == 200
    assert not any(row["member_id"] == member_id for row in response.json()["rows"])


async def test_trends_buckets_attendance_by_week_and_computes_show_rate(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, attendance_taken_at=datetime.now(UTC))
    came_id = await _seed_member(db_sessionmaker, discord_id=7001, display_name="Shows")
    no_show_id = await _seed_member(db_sessionmaker, discord_id=7002, display_name="Ghosts")
    await _seed_signup(db_sessionmaker, event_id=event_id, member_id=came_id, status="signed", attended=True)
    await _seed_signup(db_sessionmaker, event_id=event_id, member_id=no_show_id, status="signed", attended=False)
    await login_as(member_client, discord_state, discord_id=54, roles=[GM_ROLE_ID])
    response = await member_client.get("/api/attendance/trends", params={"window": "all_time"})
    assert response.status_code == 200
    points = response.json()["points"]
    assert len(points) == 1
    assert points[0]["attendees"] == 1
    assert points[0]["signed_up"] == 2
    assert points[0]["show_rate"] == 0.5


async def test_trends_two_raids_in_a_week_with_full_attendance_is_100_percent(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Two members attending both of a week's raids show 100%, not the old distinct-attendees/row-count mismatch."""
    first_raid = await _seed_event(db_sessionmaker, title="Molten Core", attendance_taken_at=datetime.now(UTC))
    second_raid = await _seed_event(db_sessionmaker, title="Blackwing Lair", attendance_taken_at=datetime.now(UTC))
    attendee_a = await _seed_member(db_sessionmaker, discord_id=7101, display_name="Alpha")
    attendee_b = await _seed_member(db_sessionmaker, discord_id=7102, display_name="Beta")
    for raid_event_id in (first_raid, second_raid):
        for member_id in (attendee_a, attendee_b):
            await _seed_signup(
                db_sessionmaker, event_id=raid_event_id, member_id=member_id, status="signed", attended=True
            )
    await login_as(member_client, discord_state, discord_id=56, roles=[GM_ROLE_ID])
    response = await member_client.get("/api/attendance/trends", params={"window": "all_time"})
    assert response.status_code == 200
    points = response.json()["points"]
    assert len(points) == 1
    assert points[0]["attendees"] == 2  # distinct members, a separate display metric
    assert points[0]["signed_up"] == 4  # 2 members x 2 raids
    assert points[0]["show_rate"] == 1.0  # perfect attendance, not 50%
