"""HTTP-level tests for ``/api/event-series``: officer auth, validation, series-edit/end-series occurrence rules."""

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

from sidequest_common.models import EventSeries, EventSignup, GuildEvent, Member
from tests.conftest import GUILD_ID
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SERIES_BODY = {
    "kind": "raid",
    "title": "Molten Core",
    "location": "Molten Core",
    "size": 40,
    "notes": None,
    "weekdays": [4],
    "interval_weeks": 1,
    "start_time": "19:00",
    "timezone": "America/Chicago",
    "duration_minutes": 180,
    "starts_on": "2026-01-02",
}


async def _seed_series(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    weekdays: list[int] | None = None,
    starts_on: date = date(2026, 1, 2),
    interval_weeks: int = 1,
    timezone: str = "UTC",
    start_time: time = time(19, 0),
    duration_minutes: int | None = 180,
    until: date | None = None,
    skipped_dates: list[str] | None = None,
) -> EventSeries:
    async with db_sessionmaker() as session:
        series = EventSeries(
            kind="raid",
            title="Molten Core",
            location="Molten Core",
            size=40,
            notes=None,
            weekdays=weekdays or [4],
            interval_weeks=interval_weeks,
            start_time=start_time,
            duration_minutes=duration_minutes,
            timezone=timezone,
            starts_on=starts_on,
            until=until,
            skipped_dates=skipped_dates or [],
            active=True,
        )
        session.add(series)
        await session.commit()
        await session.refresh(series)
        return series


async def _seed_occurrence(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    series: EventSeries,
    *,
    occurrence_date: date,
    starts_at: datetime,
    title: str | None = None,
    status: str = "scheduled",
    series_detached: bool = False,
    with_signup: bool = False,
) -> GuildEvent:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind=series.kind,
            title=title or series.title,
            location=series.location,
            starts_at=starts_at,
            ends_at=None,
            size=series.size,
            status=status,
            notes=series.notes,
            series_id=series.id,
            occurrence_date=occurrence_date,
            series_detached=series_detached,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        if with_signup:
            member = Member(discord_id=800_000_000 + occurrence_date.toordinal(), username="tester")
            session.add(member)
            await session.flush()
            session.add(EventSignup(event_id=event.id, member_id=member.id, status="signed"))
            await session.commit()
        return event


async def test_anonymous_create_is_401(member_client: AsyncTestClient) -> None:
    response = await member_client.post("/api/event-series", json=_SERIES_BODY)
    assert response.status_code == 401


async def test_non_officer_create_is_403(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=3001, roles=[])
    response = await member_client.post("/api/event-series", json=_SERIES_BODY)
    assert response.status_code == 403


async def test_create_series_materializes_and_returns_summary(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=3002, roles=[OFFICER_ROLE_ID])
    response = await member_client.post("/api/event-series", json=_SERIES_BODY)
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "raid"
    assert body["rule"]["weekdays"] == [4]
    assert body["rule"]["interval_weeks"] == 1
    assert body["rule"]["start_time"] == "19:00"
    assert body["rule"]["timezone"] == "America/Chicago"
    assert body["active"] is True
    assert body["next_starts_at"] is not None

    listed = await member_client.get("/api/event-series")
    assert listed.status_code == 200
    assert any(series["id"] == body["id"] for series in listed.json())

    events = await member_client.get("/api/events", params={"when": "upcoming"})
    occurrences = [event for event in events.json() if event["series"] and event["series"]["id"] == body["id"]]
    assert occurrences
    for occurrence in occurrences:
        assert occurrence["series"]["weekdays"] == [4]
        assert occurrence["series"]["start_time"] == "19:00"


async def test_create_series_rejects_unknown_timezone(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=3003, roles=[OFFICER_ROLE_ID])
    response = await member_client.post("/api/event-series", json={**_SERIES_BODY, "timezone": "Not/AZone"})
    assert response.status_code == 400


async def test_create_series_rejects_empty_weekdays(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=3004, roles=[OFFICER_ROLE_ID])
    response = await member_client.post("/api/event-series", json={**_SERIES_BODY, "weekdays": []})
    assert response.status_code == 400


async def test_create_series_rejects_until_before_starts_on(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=3005, roles=[OFFICER_ROLE_ID])
    response = await member_client.post(
        "/api/event-series", json={**_SERIES_BODY, "starts_on": "2026-02-01", "until": "2026-01-01"}
    )
    assert response.status_code == 400


async def test_patch_occurrence_detaches_it_from_series(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    series = await _seed_series(db_sessionmaker)
    occurrence = await _seed_occurrence(
        db_sessionmaker, series, occurrence_date=date(2026, 1, 2), starts_at=datetime(2026, 1, 2, 19, tzinfo=UTC)
    )
    await login_as(member_client, discord_state, discord_id=3010, roles=[OFFICER_ROLE_ID])
    response = await member_client.patch(f"/api/events/{occurrence.id}", json={"title": "Special Night"})
    assert response.status_code == 200
    assert response.json()["series"] is None
    assert response.json()["title"] == "Special Night"


async def test_delete_occurrence_skips_its_date(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    series = await _seed_series(db_sessionmaker)
    occurrence = await _seed_occurrence(
        db_sessionmaker, series, occurrence_date=date(2026, 1, 2), starts_at=datetime(2026, 1, 2, 19, tzinfo=UTC)
    )
    await login_as(member_client, discord_state, discord_id=3011, roles=[OFFICER_ROLE_ID])
    response = await member_client.delete(f"/api/events/{occurrence.id}")
    assert response.status_code == 204

    async with db_sessionmaker() as session:
        refreshed = await session.get(EventSeries, series.id)
        assert refreshed is not None
        assert "2026-01-02" in refreshed.skipped_dates


async def test_series_content_edit_updates_future_non_detached_occurrences_only(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    today = date.today()
    far_future = today + timedelta(days=60)
    series = await _seed_series(db_sessionmaker, starts_on=date(2020, 1, 3))
    future = await _seed_occurrence(
        db_sessionmaker,
        series,
        occurrence_date=far_future,
        starts_at=datetime.combine(far_future, time(19), tzinfo=UTC),
    )
    detached = await _seed_occurrence(
        db_sessionmaker,
        series,
        occurrence_date=far_future + timedelta(days=7),
        starts_at=datetime.combine(far_future + timedelta(days=7), time(19), tzinfo=UTC),
        series_detached=True,
    )
    past = await _seed_occurrence(
        db_sessionmaker, series, occurrence_date=date(2020, 1, 3), starts_at=datetime(2020, 1, 3, 19, tzinfo=UTC)
    )

    await login_as(member_client, discord_state, discord_id=3020, roles=[OFFICER_ROLE_ID])
    response = await member_client.patch(f"/api/event-series/{series.id}", json={"title": "Onyxia's Lair"})
    assert response.status_code == 200

    async with db_sessionmaker() as session:
        future_refreshed = await session.get(GuildEvent, future.id)
        detached_refreshed = await session.get(GuildEvent, detached.id)
        past_refreshed = await session.get(GuildEvent, past.id)
        assert future_refreshed is not None
        assert detached_refreshed is not None
        assert past_refreshed is not None
        assert future_refreshed.title == "Onyxia's Lair"
        assert detached_refreshed.title == "Molten Core"
        assert past_refreshed.title == "Molten Core"


async def test_series_schedule_change_retimes_deletes_and_cancels_occurrences(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    today = date.today()
    far_future = today + timedelta(days=60)
    friday = far_future + timedelta(days=(4 - far_future.weekday()) % 7)
    saturday = friday + timedelta(days=1)
    series = await _seed_series(db_sessionmaker, weekdays=[4], starts_on=date(2020, 1, 3))
    matching = await _seed_occurrence(
        db_sessionmaker, series, occurrence_date=friday, starts_at=datetime.combine(friday, time(19), tzinfo=UTC)
    )
    no_signups = await _seed_occurrence(
        db_sessionmaker, series, occurrence_date=saturday, starts_at=datetime.combine(saturday, time(19), tzinfo=UTC)
    )
    with_signups = await _seed_occurrence(
        db_sessionmaker,
        series,
        occurrence_date=saturday + timedelta(days=7),
        starts_at=datetime.combine(saturday + timedelta(days=7), time(19), tzinfo=UTC),
        with_signup=True,
    )

    await login_as(member_client, discord_state, discord_id=3030, roles=[OFFICER_ROLE_ID])
    response = await member_client.patch(f"/api/event-series/{series.id}", json={"start_time": "20:00"})
    assert response.status_code == 200

    async with db_sessionmaker() as session:
        retimed = await session.get(GuildEvent, matching.id)
        assert retimed is not None
        assert retimed.starts_at == datetime.combine(friday, time(20), tzinfo=UTC)

        assert await session.get(GuildEvent, no_signups.id) is None

        cancelled = await session.get(GuildEvent, with_signups.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert cancelled.series_detached is True


async def test_end_series_deletes_signupless_cancels_with_signups_keeps_past(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    today = date.today()
    far_future = today + timedelta(days=60)
    series = await _seed_series(db_sessionmaker, starts_on=date(2020, 1, 3))
    future_no_signups = await _seed_occurrence(
        db_sessionmaker,
        series,
        occurrence_date=far_future,
        starts_at=datetime.combine(far_future, time(19), tzinfo=UTC),
    )
    future_with_signups = await _seed_occurrence(
        db_sessionmaker,
        series,
        occurrence_date=far_future + timedelta(days=7),
        starts_at=datetime.combine(far_future + timedelta(days=7), time(19), tzinfo=UTC),
        with_signup=True,
    )
    past = await _seed_occurrence(
        db_sessionmaker, series, occurrence_date=date(2020, 1, 3), starts_at=datetime(2020, 1, 3, 19, tzinfo=UTC)
    )

    await login_as(member_client, discord_state, discord_id=3040, roles=[OFFICER_ROLE_ID])
    response = await member_client.delete(f"/api/event-series/{series.id}")
    assert response.status_code == 204

    async with db_sessionmaker() as session:
        assert await session.get(GuildEvent, future_no_signups.id) is None
        cancelled = await session.get(GuildEvent, future_with_signups.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        kept = await session.get(GuildEvent, past.id)
        assert kept is not None
        assert kept.status == "scheduled"
        assert await session.get(EventSeries, series.id) is None


async def test_update_series_rejects_unknown_timezone(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    series = await _seed_series(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=3050, roles=[OFFICER_ROLE_ID])
    response = await member_client.patch(f"/api/event-series/{series.id}", json={"timezone": "Not/AZone"})
    assert response.status_code == 400


async def test_event_sync_pending_includes_freshly_materialized_occurrence(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_series(db_sessionmaker, starts_on=date.today(), timezone="UTC")
    pending = await client.get(f"/api/guilds/{GUILD_ID}/event-sync/")
    assert pending.status_code == 200
    assert pending.json()["pushes"]


async def test_footer_includes_every_friday_for_weekly_series(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_series(db_sessionmaker, starts_on=date.today(), interval_weeks=1, timezone="UTC")
    pending = await client.get(f"/api/guilds/{GUILD_ID}/event-sync/")
    assert "Every Friday" in pending.json()["pushes"][0]["description"]


async def test_footer_includes_every_other_friday_for_biweekly_series(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_series(db_sessionmaker, starts_on=date.today(), interval_weeks=2, timezone="UTC")
    pending = await client.get(f"/api/guilds/{GUILD_ID}/event-sync/")
    assert "Every other Friday" in pending.json()["pushes"][0]["description"]


async def test_one_off_event_has_null_series(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind="social",
            title="Guild Game Night",
            location="",
            starts_at=datetime.now(UTC) + timedelta(days=1),
            size=None,
            status="scheduled",
            notes=None,
        )
        session.add(event)
        await session.commit()
    response = await member_client.get("/api/events", params={"when": "upcoming"})
    assert all(event["series"] is None for event in response.json() if event["title"] == "Guild Game Night")
