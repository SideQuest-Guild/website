"""Repeating guild event series persistence, plus the series-edit/end-series occurrence rules.

See ``local://event-series-contract.md`` (Series edits, Occurrence edits).
"""

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import NotFoundException, ValidationException
from sqlalchemy import func, select

from sidequest_api.domain.event_series.materializer import materialize_series, occurrence_matches
from sidequest_common.models import DiscordEventTombstone, EventSeries, EventSignup, GuildEvent
from sidequest_common.schemas import EventSeriesCreate, EventSeriesSummary, EventSeriesUpdate, event_ep

if TYPE_CHECKING:
    from uuid import UUID

CONTENT_FIELDS = ("kind", "title", "location", "size", "ep_override", "notes", "duration_minutes")
SCHEDULE_FIELDS = ("weekdays", "interval_weeks", "start_time", "timezone", "starts_on", "until")


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _format_time(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def _summary(series: EventSeries, next_starts_at: datetime | None) -> EventSeriesSummary:
    return EventSeriesSummary.model_validate(
        {
            "id": series.id,
            "kind": series.kind,
            "title": series.title,
            "location": series.location,
            "size": series.size,
            "ep": event_ep(series.kind, series.ep_override),
            "ep_override": series.ep_override,
            "notes": series.notes,
            "rule": {
                "weekdays": series.weekdays,
                "interval_weeks": series.interval_weeks,
                "start_time": _format_time(series.start_time),
                "timezone": series.timezone,
                "duration_minutes": series.duration_minutes,
                "starts_on": series.starts_on,
                "until": series.until,
            },
            "active": series.active,
            "next_starts_at": next_starts_at,
        }
    )


class EventSeriesRepository(SQLAlchemyAsyncRepository[EventSeries]):
    """EventSeries persistence."""

    model_type = EventSeries


class EventSeriesService(SQLAlchemyAsyncRepositoryService[EventSeries]):
    """Repeating event series CRUD, and the occurrence edits a series create/update/end triggers."""

    repository_type = EventSeriesRepository

    async def list_active(self) -> list[EventSeriesSummary]:
        """Every active series, each with its soonest future occurrence's ``starts_at`` (``None`` if it has none)."""
        session = self.repository.session
        series_list = list(
            (await session.execute(select(EventSeries).where(EventSeries.active.is_(True)))).scalars().all()
        )
        next_by_series = await self._next_starts_at([series.id for series in series_list])
        return [_summary(series, next_by_series.get(series.id)) for series in series_list]

    async def get_series_or_404(self, series_id: UUID) -> EventSeries:
        """The series, or 404."""
        series = await self.get_one_or_none(id=series_id)
        if series is None:
            msg = f"No event series {series_id}"
            raise NotFoundException(msg)
        return series

    async def create_series(self, data: EventSeriesCreate) -> EventSeriesSummary:
        """Create a series and materialize its occurrences immediately."""
        series = EventSeries(
            kind=data.kind.value,
            title=data.title,
            location=data.location,
            size=data.size,
            ep_override=data.ep_override,
            notes=data.notes,
            weekdays=sorted(set(data.weekdays)),
            interval_weeks=data.interval_weeks,
            start_time=_parse_time(data.start_time),
            duration_minutes=data.duration_minutes,
            timezone=data.timezone,
            starts_on=data.starts_on,
            until=data.until,
            skipped_dates=[],
            active=True,
        )
        series = await self.create(series, auto_commit=True)
        await materialize_series(self.repository.session, series, now=datetime.now(UTC))
        next_starts_at = (await self._next_starts_at([series.id])).get(series.id)
        return _summary(series, next_starts_at)

    async def update_series(self, series_id: UUID, data: EventSeriesUpdate) -> EventSeriesSummary:
        """Apply the present fields of ``data``, retime/retire affected occurrences, then materialize.

        Content fields (kind/title/location/size/notes/duration_minutes) are copied onto future scheduled
        non-detached occurrences as-is. Schedule fields (weekdays/interval_weeks/start_time/timezone/starts_on/
        until) re-time matching future occurrences and delete (no signups) or cancel+detach (has signups) ones
        that no longer match the new rule.
        """
        series = await self.get_series_or_404(series_id)
        changes = data.model_dump(exclude_unset=True)
        schedule_changed = any(field in changes for field in SCHEDULE_FIELDS)
        content_changed = any(field in changes for field in CONTENT_FIELDS)
        if "weekdays" in changes:
            changes["weekdays"] = sorted(set(changes["weekdays"]))
        if "start_time" in changes:
            changes["start_time"] = _parse_time(changes["start_time"])
        for field, value in changes.items():
            setattr(series, field, value)
        if series.until is not None and series.until < series.starts_on:
            msg = "until must not be before starts_on"
            raise ValidationException(msg)
        series = await self.update(series, auto_commit=True)

        now = datetime.now(UTC)
        if schedule_changed:
            await self._retime_or_retire_for_schedule_change(series, now)
        elif content_changed:
            await self._apply_content_to_future_occurrences(series, now)

        await materialize_series(self.repository.session, series, now=now)
        next_starts_at = (await self._next_starts_at([series.id])).get(series.id)
        return _summary(series, next_starts_at)

    async def end_series(self, series_id: UUID) -> None:
        """End a series: delete signup-less future occurrences, cancel those with signups, keep past ones."""
        series = await self.get_series_or_404(series_id)
        now = datetime.now(UTC)
        for occurrence in await self._future_occurrences(series.id, now):
            await self._retire_occurrence(occurrence, detach=False)
        await self.repository.session.commit()
        await self.delete(series_id, auto_commit=True)

    async def _future_occurrences(self, series_id: UUID, now: datetime) -> list[GuildEvent]:
        session = self.repository.session
        statement = select(GuildEvent).where(
            GuildEvent.series_id == series_id,
            GuildEvent.series_detached.is_(False),
            GuildEvent.status == "scheduled",
            GuildEvent.starts_at >= now,
        )
        return list((await session.execute(statement)).scalars().all())

    async def _retime_or_retire_for_schedule_change(self, series: EventSeries, now: datetime) -> None:
        tz = ZoneInfo(series.timezone)
        duration = timedelta(minutes=series.duration_minutes) if series.duration_minutes is not None else None
        for occurrence in await self._future_occurrences(series.id, now):
            if occurrence.occurrence_date is None:
                continue
            occurrence_date = occurrence.occurrence_date
            if occurrence_matches(series, occurrence_date):
                starts_at = datetime.combine(occurrence_date, series.start_time, tzinfo=tz).astimezone(UTC)
                occurrence.starts_at = starts_at
                occurrence.ends_at = starts_at + duration if duration is not None else None
            else:
                await self._retire_occurrence(occurrence, detach=True)
        await self.repository.session.commit()

    async def _apply_content_to_future_occurrences(self, series: EventSeries, now: datetime) -> None:
        duration = timedelta(minutes=series.duration_minutes) if series.duration_minutes is not None else None
        for occurrence in await self._future_occurrences(series.id, now):
            occurrence.kind = series.kind
            occurrence.title = series.title
            occurrence.location = series.location
            occurrence.size = series.size
            occurrence.ep_override = series.ep_override
            occurrence.notes = series.notes
            occurrence.ends_at = occurrence.starts_at + duration if duration is not None else None
        await self.repository.session.commit()

    async def _retire_occurrence(self, occurrence: GuildEvent, *, detach: bool) -> None:
        """Delete a signup-less occurrence (tombstoning a linked Discord event), or cancel one with signups."""
        session = self.repository.session
        signup_count = (
            await session.execute(
                select(func.count()).select_from(EventSignup).where(EventSignup.event_id == occurrence.id)
            )
        ).scalar_one()
        if signup_count > 0:
            occurrence.status = "cancelled"
            if detach:
                occurrence.series_detached = True
        else:
            if occurrence.discord_event_id is not None:
                session.add(DiscordEventTombstone(discord_event_id=occurrence.discord_event_id))
            await session.delete(occurrence)

    async def _next_starts_at(self, series_ids: list[UUID]) -> dict[UUID, datetime | None]:
        if not series_ids:
            return {}
        session = self.repository.session
        now = datetime.now(UTC)
        statement = (
            select(GuildEvent.series_id, func.min(GuildEvent.starts_at))
            .where(
                GuildEvent.series_id.in_(series_ids),
                GuildEvent.status == "scheduled",
                GuildEvent.starts_at >= now,
            )
            .group_by(GuildEvent.series_id)
        )
        rows = (await session.execute(statement)).all()
        return dict(rows)
