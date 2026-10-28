"""Materializes ``GuildEvent`` occurrences for active ``EventSeries`` rows up to a 14-day horizon.

See ``local://event-series-contract.md`` (Materialization section). Runs after series create/update and at the
start of both ``GET /api/events`` and the event-sync pending GET, so Discord and the site stay filled with real,
signable occurrences without anyone needing to open the officer form. Each occurrence creation commits on its own:
if another request materialized the same date first, the unique constraint on (series_id, occurrence_date) raises
``IntegrityError``, which is caught and ignored, without losing occurrences this call already created.
"""

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from advanced_alchemy.exceptions import IntegrityError
from sqlalchemy import select

from sidequest_common.models import EventSeries, GuildEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

HORIZON = timedelta(days=14)


def _monday_of(day: date) -> date:
    """The Monday starting ``day``'s ISO week."""
    return day - timedelta(days=day.weekday())


def occurrence_matches(series: EventSeries, occurrence_date: date) -> bool:
    """Whether ``occurrence_date`` is a valid occurrence of ``series`` under its *current* rule.

    Used both to pick materialization candidates and, on a schedule edit, to decide whether an existing
    occurrence still belongs to the series (re-time it) or not (delete/cancel it).
    """
    if occurrence_date < series.starts_on:
        return False
    if series.until is not None and occurrence_date > series.until:
        return False
    if occurrence_date.weekday() not in series.weekdays:
        return False
    if occurrence_date.isoformat() in series.skipped_dates:
        return False
    week_diff = (_monday_of(occurrence_date) - _monday_of(series.starts_on)).days // 7
    return week_diff % series.interval_weeks == 0


def _candidate_dates(series: EventSeries, today: date, horizon_end: date) -> list[date]:
    end = horizon_end if series.until is None else min(horizon_end, series.until)
    start = max(series.starts_on, today)
    if start > end:
        return []
    return [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if occurrence_matches(series, start + timedelta(days=offset))
    ]


async def materialize_series(session: AsyncSession, series: EventSeries, *, now: datetime) -> None:
    """Create any missing occurrences for one active series within the horizon.

    Deactivates the series instead if ``until`` is already before today in the series' own timezone. ``now`` is
    an injected UTC clock so callers (and tests) can materialize as of a specific instant.
    """
    tz = ZoneInfo(series.timezone)
    local_now = now.astimezone(tz)
    today = local_now.date()
    if series.until is not None and series.until < today:
        series.active = False
        await session.commit()
        return
    candidates = _candidate_dates(series, today, (local_now + HORIZON).date())
    if not candidates:
        return
    existing = set(
        (
            await session.execute(
                select(GuildEvent.occurrence_date).where(
                    GuildEvent.series_id == series.id,
                    GuildEvent.occurrence_date.in_(candidates),
                )
            )
        )
        .scalars()
        .all()
    )
    duration = timedelta(minutes=series.duration_minutes) if series.duration_minutes is not None else None
    for occurrence_date in candidates:
        if occurrence_date in existing:
            continue
        starts_at = datetime.combine(occurrence_date, series.start_time, tzinfo=tz).astimezone(UTC)
        session.add(
            GuildEvent(
                kind=series.kind,
                title=series.title,
                location=series.location,
                starts_at=starts_at,
                ends_at=starts_at + duration if duration is not None else None,
                size=series.size,
                status="scheduled",
                notes=series.notes,
                series_id=series.id,
                occurrence_date=occurrence_date,
                series_detached=False,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # Another request materialized this date between our lookup and our insert.
            await session.rollback()


async def materialize_all(session: AsyncSession, *, now: datetime | None = None) -> None:
    """Materialize every active series. Call at the start of any read that must stay filled for the next 14 days."""
    now = now or datetime.now(UTC)
    series_list = list((await session.execute(select(EventSeries).where(EventSeries.active.is_(True)))).scalars().all())
    for series in series_list:
        await materialize_series(session, series, now=now)
