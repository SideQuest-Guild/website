"""Direct tests of the materializer's date math: DST-safe UTC conversion, interval skipping, idempotency."""

from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_api.domain.event_series.materializer import materialize_all, materialize_series
from sidequest_common.models import EventSeries, GuildEvent

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _make_series(
    *,
    weekdays: list[int],
    starts_on: date,
    timezone: str = "UTC",
    interval_weeks: int = 1,
    start_time: time = time(19, 0),
    until: date | None = None,
    skipped_dates: list[str] | None = None,
    active: bool = True,
) -> EventSeries:
    return EventSeries(
        kind="raid",
        title="Molten Core",
        location="Molten Core",
        size=40,
        notes=None,
        weekdays=weekdays,
        interval_weeks=interval_weeks,
        start_time=start_time,
        duration_minutes=180,
        timezone=timezone,
        starts_on=starts_on,
        until=until,
        skipped_dates=skipped_dates or [],
        active=active,
    )


async def _occurrence_dates(db_sessionmaker: async_sessionmaker[AsyncSession], series_id: UUID) -> set[date]:
    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(GuildEvent.occurrence_date).where(GuildEvent.series_id == series_id)))
            .scalars()
            .all()
        )
        return {row for row in rows if row is not None}


async def test_weekly_friday_materializes_across_dst_boundary_with_shifted_utc_hour(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """2026-10-30 (CDT, UTC-5) and 2026-11-06 (CST, UTC-6, after DST ends 2026-11-01) land at different UTC hours."""
    async with db_sessionmaker() as session:
        series = _make_series(
            weekdays=[4],
            starts_on=date(2026, 10, 30),
            timezone="America/Chicago",
            start_time=time(19, 0),
        )
        session.add(series)
        await session.commit()
        await session.refresh(series)
        series_id = series.id
        now = datetime(2026, 10, 27, tzinfo=UTC)
        await materialize_series(session, series, now=now)

    async with db_sessionmaker() as session:
        events = list(
            (await session.execute(select(GuildEvent).where(GuildEvent.series_id == series_id))).scalars().all()
        )
    by_date = {event.occurrence_date: event.starts_at for event in events}
    assert set(by_date) == {date(2026, 10, 30), date(2026, 11, 6)}
    assert by_date[date(2026, 10, 30)] == datetime(2026, 10, 31, 0, 0, tzinfo=UTC)
    assert by_date[date(2026, 11, 6)] == datetime(2026, 11, 7, 1, 0, tzinfo=UTC)


async def test_interval_two_skips_alternate_week_anchored_on_starts_on(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_sessionmaker() as session:
        series = _make_series(weekdays=[0], starts_on=date(2026, 1, 5), interval_weeks=2)
        session.add(series)
        await session.commit()
        await session.refresh(series)
        series_id = series.id
        await materialize_series(session, series, now=datetime(2026, 1, 5, tzinfo=UTC))

    dates = await _occurrence_dates(db_sessionmaker, series_id)
    assert dates == {date(2026, 1, 5), date(2026, 1, 19)}


async def test_multiple_weekdays_all_materialize(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with db_sessionmaker() as session:
        series = _make_series(weekdays=[0, 2, 4], starts_on=date(2026, 1, 5))
        session.add(series)
        await session.commit()
        await session.refresh(series)
        series_id = series.id
        await materialize_series(session, series, now=datetime(2026, 1, 5, tzinfo=UTC))

    dates = await _occurrence_dates(db_sessionmaker, series_id)
    assert dates == {
        date(2026, 1, 5),
        date(2026, 1, 7),
        date(2026, 1, 9),
        date(2026, 1, 12),
        date(2026, 1, 14),
        date(2026, 1, 16),
        date(2026, 1, 19),
    }


async def test_until_in_the_past_deactivates_series_and_creates_nothing(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_sessionmaker() as session:
        series = _make_series(weekdays=[4], starts_on=date(2026, 1, 2), until=date(2026, 1, 20), timezone="UTC")
        session.add(series)
        await session.commit()
        await session.refresh(series)
        series_id = series.id
        await materialize_series(session, series, now=datetime(2026, 2, 1, tzinfo=UTC))
        assert series.active is False

    async with db_sessionmaker() as session:
        count = len(
            (await session.execute(select(GuildEvent).where(GuildEvent.series_id == series_id))).scalars().all()
        )
    assert count == 0


async def test_repeated_materialization_is_idempotent(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with db_sessionmaker() as session:
        series = _make_series(weekdays=[4], starts_on=date(2026, 1, 2))
        session.add(series)
        await session.commit()
        await session.refresh(series)
        series_id = series.id
        now = datetime(2026, 1, 2, tzinfo=UTC)
        await materialize_series(session, series, now=now)
        first_count = len(
            (await session.execute(select(GuildEvent).where(GuildEvent.series_id == series_id))).scalars().all()
        )
        await materialize_series(session, series, now=now)
        second_count = len(
            (await session.execute(select(GuildEvent).where(GuildEvent.series_id == series_id))).scalars().all()
        )
    assert first_count > 0
    assert first_count == second_count


async def test_skipped_date_is_not_recreated(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with db_sessionmaker() as session:
        series = _make_series(weekdays=[4], starts_on=date(2026, 1, 2), skipped_dates=["2026-01-02"])
        session.add(series)
        await session.commit()
        await session.refresh(series)
        series_id = series.id
        await materialize_series(session, series, now=datetime(2026, 1, 2, tzinfo=UTC))

    dates = await _occurrence_dates(db_sessionmaker, series_id)
    assert date(2026, 1, 2) not in dates
    assert date(2026, 1, 9) in dates


async def test_materialize_all_only_touches_active_series(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with db_sessionmaker() as session:
        active = _make_series(weekdays=[4], starts_on=date(2026, 1, 2))
        inactive = _make_series(weekdays=[4], starts_on=date(2026, 1, 2), active=False)
        session.add_all([active, inactive])
        await session.commit()
        await session.refresh(active)
        await session.refresh(inactive)
        active_id, inactive_id = active.id, inactive.id
        await materialize_all(session, now=datetime(2026, 1, 2, tzinfo=UTC))

    assert await _occurrence_dates(db_sessionmaker, active_id)
    assert not await _occurrence_dates(db_sessionmaker, inactive_id)
