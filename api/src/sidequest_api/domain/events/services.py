"""Guild event, signup, and raid-chart persistence and queries."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import HTTPException, NotFoundException, ValidationException
from litestar.status_codes import HTTP_409_CONFLICT
from sqlalchemy import func, or_, select

from sidequest_api.domain.event_series.materializer import materialize_all
from sidequest_api.lib.discord import avatar_url
from sidequest_common.models import DiscordEventTombstone, EventSeries, EventSignup, GuildEvent, Member
from sidequest_common.schemas import (
    ROLE_KINDS,
    ChartUpdate,
    EventCounts,
    EventCreate,
    EventDetail,
    EventKind,
    EventSummary,
    EventUpdate,
    Signup,
    SignupUpsert,
)

if TYPE_CHECKING:
    from uuid import UUID

UPCOMING_LOOKBACK = timedelta(hours=6)
PAST_LIMIT = 50


def _series_ref(event: GuildEvent) -> dict[str, object] | None:
    if event.series_id is None or event.series_detached or event.series is None:
        return None
    return {
        "id": event.series.id,
        "weekdays": event.series.weekdays,
        "interval_weeks": event.series.interval_weeks,
        "start_time": event.series.start_time.strftime("%H:%M"),
        "timezone": event.series.timezone,
    }


def _event_summary_fields(event: GuildEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "kind": event.kind,
        "title": event.title,
        "location": event.location,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "size": event.size,
        "status": event.status,
        "notes": event.notes,
        "series": _series_ref(event),
    }


def _to_signup_schema(signup: EventSignup, member: Member) -> Signup:
    member_avatar = avatar_url(member.discord_id, member.avatar_hash)
    return Signup.model_validate(
        {
            "id": signup.id,
            "member": {"display_name": member.display_name, "avatar_url": member_avatar},
            "character": signup.character,
            "class": signup.wow_class,
            "role": signup.role,
            "status": signup.status,
            "comment": signup.comment,
            "group": signup.chart_group,
            "bench": signup.bench,
            "updated_at": signup.updated_at,
        }
    )


def _counts_from_rows(rows: list[tuple[str | None, str, int]]) -> EventCounts:
    """``rows`` are ``(role, status, count)`` for one event. tank/healer/dps/signed only count ``signed``."""
    tank = healer = dps = signed = tentative = absent = 0
    for role, status, count in rows:
        if status == "tentative":
            tentative += count
        elif status == "absent":
            absent += count
        elif status == "signed":
            signed += count
            if role == "tank":
                tank += count
            elif role == "healer":
                healer += count
            elif role == "dps":
                dps += count
    return EventCounts(tank=tank, healer=healer, dps=dps, signed=signed, tentative=tentative, absent=absent)


class EventsRepository(SQLAlchemyAsyncRepository[GuildEvent]):
    """GuildEvent persistence."""

    model_type = GuildEvent


class EventsService(SQLAlchemyAsyncRepositoryService[GuildEvent]):
    """Guild event CRUD plus the read-side views (list with headcounts, detail with roster)."""

    repository_type = EventsRepository

    async def list_summaries(
        self, when: Literal["upcoming", "past"], kind: EventKind | None = None
    ) -> list[EventSummary]:
        """Events for the given window, with headcounts. Upcoming is ascending; past is descending, limit 50."""
        session = self.repository.session
        await materialize_all(session)
        statement = select(GuildEvent)
        cutoff = datetime.now(UTC) - UPCOMING_LOOKBACK
        if when == "upcoming":
            statement = statement.where(GuildEvent.starts_at >= cutoff, GuildEvent.status != "completed").order_by(
                GuildEvent.starts_at.asc()
            )
        else:
            statement = (
                statement.where(or_(GuildEvent.starts_at < cutoff, GuildEvent.status == "completed"))
                .order_by(GuildEvent.starts_at.desc())
                .limit(PAST_LIMIT)
            )
        if kind is not None:
            statement = statement.where(GuildEvent.kind == kind.value)
        events = list((await session.execute(statement)).scalars().all())
        counts = await self._counts_for([event.id for event in events])
        return [
            EventSummary.model_validate({**_event_summary_fields(event), "counts": counts[event.id]})
            for event in events
        ]

    async def get_detail(self, event_id: UUID, *, viewer: Member | None) -> EventDetail:
        """An event with its full roster and the viewer's own signup (``None`` if anonymous or not signed up)."""
        event = await self.get_event_or_404(event_id)
        session = self.repository.session
        statement = (
            select(EventSignup, Member)
            .join(Member, EventSignup.member_id == Member.id)
            .where(EventSignup.event_id == event_id)
        )
        rows = (await session.execute(statement)).all()
        signups = [_to_signup_schema(signup, member) for signup, member in rows]
        my_signup = None
        if viewer is not None:
            own = next(((signup, member) for signup, member in rows if member.id == viewer.id), None)
            if own is not None:
                my_signup = _to_signup_schema(*own)
        counts = (await self._counts_for([event_id]))[event_id]
        return EventDetail.model_validate(
            {**_event_summary_fields(event), "counts": counts, "signups": signups, "my_signup": my_signup}
        )

    async def get_event_or_404(self, event_id: UUID) -> GuildEvent:
        """The event, or 404."""
        event = await self.get_one_or_none(id=event_id)
        if event is None:
            msg = f"No event {event_id}"
            raise NotFoundException(msg)
        return event

    async def create_event(self, data: EventCreate) -> GuildEvent:
        """Create a scheduled guild event."""
        event = GuildEvent(
            kind=data.kind.value,
            title=data.title,
            location=data.location,
            starts_at=data.starts_at,
            ends_at=data.ends_at,
            size=data.size,
            notes=data.notes,
        )
        return await self.create(event, auto_commit=True)

    async def update_event(self, event_id: UUID, data: EventUpdate) -> GuildEvent:
        """Apply the present fields of ``data``. 400 if the resulting ``ends_at`` isn't after ``starts_at``.

        Editing a series occurrence detaches it: series-wide content/schedule edits stop touching it afterward.
        """
        event = await self.get_event_or_404(event_id)
        changes = data.model_dump(exclude_unset=True)
        starts_at = changes.get("starts_at", event.starts_at)
        ends_at = changes.get("ends_at", event.ends_at)
        if ends_at is not None and ends_at <= starts_at:
            msg = "ends_at must be after starts_at"
            raise ValidationException(msg)
        for field, value in changes.items():
            setattr(event, field, value)
        if event.series_id is not None:
            event.series_detached = True
        return await self.update(event, auto_commit=True)

    async def delete_event(self, event_id: UUID) -> None:
        """Delete an event and its signups; tombstone a linked Discord event in the same transaction.

        Deleting a series occurrence skips its date, so the series doesn't recreate it.
        """
        event = await self.get_event_or_404(event_id)
        if event.discord_event_id is not None:
            self.repository.session.add(DiscordEventTombstone(discord_event_id=event.discord_event_id))
        if event.series_id is not None and event.occurrence_date is not None:
            series = await self.repository.session.get(EventSeries, event.series_id)
            if series is not None and event.occurrence_date.isoformat() not in series.skipped_dates:
                series.skipped_dates = [*series.skipped_dates, event.occurrence_date.isoformat()]
        await self.delete(event_id, auto_commit=True)

    async def _counts_for(self, event_ids: list[UUID]) -> dict[UUID, EventCounts]:
        if not event_ids:
            return {}
        session = self.repository.session
        statement = (
            select(EventSignup.event_id, EventSignup.role, EventSignup.status, func.count())
            .where(EventSignup.event_id.in_(event_ids))
            .group_by(EventSignup.event_id, EventSignup.role, EventSignup.status)
        )
        rows_by_event: dict[UUID, list[tuple[str | None, str, int]]] = {event_id: [] for event_id in event_ids}
        for event_id, role, status, count in (await session.execute(statement)).all():
            rows_by_event[event_id].append((role, status, count))
        return {event_id: _counts_from_rows(rows) for event_id, rows in rows_by_event.items()}


class EventSignupsRepository(SQLAlchemyAsyncRepository[EventSignup]):
    """EventSignup persistence."""

    model_type = EventSignup


class EventSignupsService(SQLAlchemyAsyncRepositoryService[EventSignup]):
    """Member signups and the officer raid chart (group/bench placement, raid kind only)."""

    repository_type = EventSignupsRepository

    async def upsert_signup(self, event_id: UUID, member: Member, data: SignupUpsert) -> Signup:
        """Create or replace the member's signup for ``event_id``. 409 if the event isn't scheduled.

        400 if the event's kind is ``raid``/``dungeon`` and ``character``/``class``/``role`` aren't all present.
        """
        session = self.repository.session
        event = await session.get(GuildEvent, event_id)
        if event is None:
            msg = f"No event {event_id}"
            raise NotFoundException(msg)
        if event.status != "scheduled":
            msg = "Event is not open for signups"
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg)
        if event.kind in {kind.value for kind in ROLE_KINDS} and (
            data.character is None or data.wow_class is None or data.role is None
        ):
            msg = "character, class, and role are required for this event's kind"
            raise ValidationException(msg)
        existing = await self.get_one_or_none(event_id=event_id, member_id=member.id)
        fields = {
            "character": data.character,
            "wow_class": data.wow_class.value if data.wow_class is not None else None,
            "role": data.role.value if data.role is not None else None,
            "status": data.status.value,
            "comment": data.comment,
        }
        if existing is None:
            try:
                signup = await self.create(
                    EventSignup(event_id=event_id, member_id=member.id, **fields), auto_commit=True
                )
            except IntegrityError as exc:
                msg = "Signup conflict"
                raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg) from exc
        else:
            for field, value in fields.items():
                setattr(existing, field, value)
            signup = await self.update(existing, auto_commit=True)
        return _to_signup_schema(signup, member)

    async def delete_for_member(self, event_id: UUID, member: Member) -> None:
        """Remove the member's signup for ``event_id``, if any."""
        existing = await self.get_one_or_none(event_id=event_id, member_id=member.id)
        if existing is not None:
            await self.delete(existing.id, auto_commit=True)

    async def update_chart(self, event_id: UUID, signup_id: UUID, data: ChartUpdate) -> Signup:
        """Place a signup on the raid chart (group 1-8) or the bench. 409 if the event isn't a raid."""
        session = self.repository.session
        event = await session.get(GuildEvent, event_id)
        if event is None:
            msg = f"No event {event_id}"
            raise NotFoundException(msg)
        if event.kind != EventKind.RAID.value:
            msg = "The raid chart only applies to raid events"
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg)
        row = (
            await session.execute(
                select(EventSignup, Member)
                .join(Member, EventSignup.member_id == Member.id)
                .where(EventSignup.id == signup_id, EventSignup.event_id == event_id)
            )
        ).first()
        if row is None:
            msg = f"No signup {signup_id} on event {event_id}"
            raise NotFoundException(msg)
        signup, member = row
        changes = data.model_dump(exclude_unset=True)
        if "group" in changes:
            signup.chart_group = changes["group"]
        if "bench" in changes:
            signup.bench = changes["bench"]
        signup = await self.update(signup, auto_commit=True)
        return _to_signup_schema(signup, member)
