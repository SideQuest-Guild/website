"""Desired-state computation and Discord-state application for the guild event <-> Discord sync.

See ``local://guild-events-contract.md`` for the kind-aware wire contract and footer this module implements (it
generalizes an earlier raid-only sync design to every event kind). In short: the API decides what Discord should
show (``DiscordEventPush``, polled via ``list_pending``) and the bot reports back what Discord actually holds
(``DiscordEventState``, applied via ``apply_event_state``/``reconcile``). Hash columns on ``GuildEvent``
(``discord_pushed_hash``, ``discord_seen_hash``) keep the two sides from echoing each other.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update

from sidequest_api.domain.event_series.materializer import materialize_all
from sidequest_api.domain.events.services import EventsService
from sidequest_common.models import (
    DiscordEventTombstone,
    EventDiscordInterest,
    EventSeries,
    EventSignupActivity,
    GuildEvent,
)
from sidequest_common.schemas import (
    EVENT_KIND_LABELS,
    ROLE_KINDS,
    DiscordEventPush,
    DiscordEventReconcile,
    DiscordEventState,
    DiscordEventStatus,
    DiscordPushAck,
    DiscordSyncPending,
    EventCounts,
    EventKind,
    PushAction,
    SignupActivity,
)

FOOTER_HEADER = "── SideQuest event ──"
MAX_DESCRIPTION_LENGTH = 1000
DEFAULT_DURATION = timedelta(hours=3)
ACTIVITY_LIMIT = 50
ACTIVITY_MAX_AGE = timedelta(hours=24)
_SIGN_UP_PATH = "/events/detail/?id="
_ACTION_BY_STATUS: dict[str, PushAction] = {"scheduled": "upsert", "cancelled": "cancel", "completed": "complete"}
_ENDED_IN_DISCORD = (DiscordEventStatus.CANCELLED, DiscordEventStatus.COMPLETED)
_ROLE_KIND_VALUES = {kind.value for kind in ROLE_KINDS}
_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_BIWEEKLY_INTERVAL = 2
_TWO_WEEKDAYS = 2


def _truncate(text: str, limit: int) -> str:
    """``text`` cut to ``limit`` chars, with a trailing "…" if it was cut."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    return text[: limit - 1] + "…"


def _series_rule_text(series: EventSeries) -> str:
    """``"Every Friday"`` / ``"Every other Friday"``, or a joined list for multiple weekdays."""
    names = [_WEEKDAY_NAMES[day] for day in series.weekdays]
    if len(names) == 1:
        day_text = names[0]
    elif len(names) == _TWO_WEEKDAYS:
        day_text = " and ".join(names)
    else:
        day_text = ", ".join(names[:-1]) + f", and {names[-1]}"
    prefix = "Every other" if series.interval_weeks == _BIWEEKLY_INTERVAL else "Every"
    return f"{prefix} {day_text}"


def _build_footer(event: GuildEvent, counts: EventCounts, web_base_url: str) -> str:
    lines = [FOOTER_HEADER]
    kind_label = EVENT_KIND_LABELS[EventKind(event.kind)]
    parts = [kind_label]
    if event.location:
        parts.append(event.location)
    if event.size is not None:
        parts.append(f"{event.size}-player")
    if event.series_id is not None and not event.series_detached and event.series is not None:
        parts.append(_series_rule_text(event.series))
    lines.append(" · ".join(parts))
    if event.kind in _ROLE_KIND_VALUES:
        signed = f"Signed: {counts.tank} tanks · {counts.healer} healers · {counts.dps} dps"
        if counts.tentative > 0:
            signed += f" · {counts.tentative} tentative"
    else:
        signed = f"Going: {counts.signed}"
        if counts.tentative > 0:
            signed += f" · {counts.tentative} maybe"
    lines.append(signed)
    lines.append(f"Details & sign-up: {web_base_url}{_SIGN_UP_PATH}{event.id}")
    return "\n".join(lines)


def _build_description(event: GuildEvent, footer: str) -> str:
    if not event.notes:
        return footer
    budget = max(MAX_DESCRIPTION_LENGTH - len(footer) - 2, 0)
    notes = _truncate(event.notes, budget)
    if not notes:
        return footer
    return f"{notes}\n\n{footer}"


def _strip_footer(description: str | None) -> str | None:
    """``description`` with the footer (and the blank line before it, if any) removed."""
    if not description:
        return None
    index = description.find(FOOTER_HEADER)
    notes = description if index == -1 else description[:index]
    notes = notes.strip()
    return notes or None


def _extract_linked_event_id(description: str | None) -> UUID | None:
    """The event id in the footer's "Details & sign-up" link, if ``description`` has one."""
    if not description:
        return None
    index = description.find(_SIGN_UP_PATH)
    if index == -1:
        return None
    start = index + len(_SIGN_UP_PATH)
    end = start + 36
    try:
        return UUID(description[start:end])
    except ValueError:
        return None


def _push_hash(
    *, action: str, name: str, description: str, location: str, starts_at: datetime, ends_at: datetime
) -> str:
    payload = json.dumps(
        [
            action,
            name,
            description,
            location,
            starts_at.astimezone(UTC).isoformat(),
            ends_at.astimezone(UTC).isoformat(),
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _state_hash(state: DiscordEventState) -> str:
    normalized = state.model_copy(
        update={
            "starts_at": state.starts_at.astimezone(UTC),
            "ends_at": state.ends_at.astimezone(UTC) if state.ends_at is not None else None,
        }
    )
    return hashlib.sha256(normalized.model_dump_json().encode()).hexdigest()


def _desired_state(event: GuildEvent, counts: EventCounts, web_base_url: str) -> DiscordEventPush:
    footer = _build_footer(event, counts, web_base_url)
    description = _build_description(event, footer)
    name = event.title[:100]
    location = (event.location or "World of Warcraft")[:100]
    ends_at = event.ends_at or (event.starts_at + DEFAULT_DURATION)
    action = _ACTION_BY_STATUS[event.status]
    push_hash = _push_hash(
        action=action, name=name, description=description, location=location, starts_at=event.starts_at, ends_at=ends_at
    )
    return DiscordEventPush(
        event_id=event.id,
        discord_event_id=event.discord_event_id,
        thread_id=event.discord_thread_id,
        kind=EventKind(event.kind),
        action=action,
        name=name,
        title=event.title,
        description=description,
        location=location,
        starts_at=event.starts_at,
        ends_at=ends_at,
        signup_url=f"{web_base_url}{_SIGN_UP_PATH}{event.id}",
        push_hash=push_hash,
    )


def _apply_discord_fields(event: GuildEvent, state: DiscordEventState, seen_hash: str) -> None:
    event.title = state.name
    event.notes = _strip_footer(state.description)
    event.starts_at = state.starts_at
    event.ends_at = state.ends_at
    if state.location:
        event.location = state.location
    if state.status in (DiscordEventStatus.SCHEDULED, DiscordEventStatus.ACTIVE):
        event.status = "scheduled"
    elif state.status == DiscordEventStatus.CANCELLED:
        event.status = "cancelled"
        event.discord_event_id = None
    elif state.status == DiscordEventStatus.COMPLETED:
        event.status = "completed"
        event.discord_event_id = None
    event.discord_seen_hash = seen_hash


class EventSyncService(EventsService):
    """Computes desired Discord state for guild events and applies Discord-reported state back onto them.

    Subclasses ``EventsService`` (same repository/model) to reuse event lookups and ``_counts_for`` for the
    footer's "Signed"/"Going" line.
    """

    async def list_pending(self, web_base_url: str) -> DiscordSyncPending:
        """Every event whose desired Discord state is out of date, plus tombstoned event ids and unposted activity."""
        session = self.repository.session
        await materialize_all(session)
        now = datetime.now(UTC)
        events = list((await session.execute(select(GuildEvent))).scalars().all())
        counts = await self._counts_for([event.id for event in events])
        pushes = []
        for event in events:
            push = _desired_state(event, counts[event.id], web_base_url)
            if push.push_hash == event.discord_pushed_hash:
                continue
            linked = event.discord_event_id is not None
            if push.action == "upsert":
                if not linked and event.starts_at <= now:
                    continue
            elif not linked:
                continue
            pushes.append(push)
        tombstone_ids = list((await session.execute(select(DiscordEventTombstone.discord_event_id))).scalars().all())
        await self._drop_stale_unthreaded_activity(now)
        activity = await self._pending_activity()
        return DiscordSyncPending(pushes=pushes, deletions=tombstone_ids, activity=activity)

    async def _drop_stale_unthreaded_activity(self, now: datetime) -> None:
        """Delete unposted activity rows older than 24h for events with no Discord thread; they'd never post."""
        session = self.repository.session
        cutoff = now - ACTIVITY_MAX_AGE
        threadless_event_ids = select(GuildEvent.id).where(GuildEvent.discord_thread_id.is_(None))
        await session.execute(
            delete(EventSignupActivity).where(
                EventSignupActivity.posted_at.is_(None),
                EventSignupActivity.created_at < cutoff,
                EventSignupActivity.event_id.in_(threadless_event_ids),
            )
        )
        await session.commit()

    async def _pending_activity(self) -> list[SignupActivity]:
        """Unposted activity for events with a Discord thread, oldest first, capped."""
        session = self.repository.session
        statement = (
            select(EventSignupActivity, GuildEvent.discord_thread_id)
            .join(GuildEvent, EventSignupActivity.event_id == GuildEvent.id)
            .where(EventSignupActivity.posted_at.is_(None), GuildEvent.discord_thread_id.is_not(None))
            .order_by(EventSignupActivity.created_at.asc())
            .limit(ACTIVITY_LIMIT)
        )
        rows = (await session.execute(statement)).all()
        return [
            SignupActivity(
                id=activity.id,
                thread_id=thread_id,
                display_name=activity.display_name,
                action=activity.action,
                detail=activity.detail,
            )
            for activity, thread_id in rows
        ]

    async def ack_activity(self, ids: list[UUID]) -> None:
        """Mark these sign-up activity rows posted so they aren't sent again."""
        session = self.repository.session
        await session.execute(
            update(EventSignupActivity).where(EventSignupActivity.id.in_(ids)).values(posted_at=datetime.now(UTC))
        )
        await session.commit()

    async def ack(self, event_id: UUID, data: DiscordPushAck) -> None:
        """Record that the bot applied ``data.push_hash``, linking/unlinking per ``data.event``.

        If the event was deleted on the site between the push and the ack, tombstone ``data.event`` instead (the
        bot still has to clean it up in Discord).
        """
        event = await self.get_one_or_none(id=event_id)
        if event is None:
            if data.event is not None:
                await self._tombstone(data.event.id)
            return
        event.discord_pushed_hash = data.push_hash
        if data.event is not None:
            event.discord_event_id = data.event.id
            event.discord_seen_hash = _state_hash(data.event)
        else:
            event.discord_event_id = None
            event.discord_seen_hash = None
        if data.thread_id is not None:
            event.discord_thread_id = data.thread_id
        await self.update(event, auto_commit=True)

    async def report_interest(self, discord_event_id: int, user_ids: list[int]) -> None:
        """Replace the interested-user set for the guild event linked to ``discord_event_id``. No-op if unlinked."""
        event = await self.get_one_or_none(discord_event_id=discord_event_id)
        if event is None:
            return
        session = self.repository.session
        await session.execute(delete(EventDiscordInterest).where(EventDiscordInterest.event_id == event.id))
        session.add_all([EventDiscordInterest(event_id=event.id, discord_id=user_id) for user_id in user_ids])
        await session.commit()

    async def apply_event_state(self, state: DiscordEventState) -> None:
        """Apply one Discord-reported event state: find/adopt/create, then sync fields unless it's our echo."""
        seen_hash = _state_hash(state)
        event = await self.get_one_or_none(discord_event_id=state.id)
        if event is None:
            event = await self._adopt_or_create(state)
            if event is None:
                return
        if event.discord_seen_hash == seen_hash:
            return
        _apply_discord_fields(event, state, seen_hash)
        await self.update(event, auto_commit=True)

    async def handle_deleted_event(self, event_id: int) -> None:
        """A Discord event is gone (explicit delete, or missing from a reconcile): unlink and cancel if scheduled."""
        event = await self.get_one_or_none(discord_event_id=event_id)
        if event is None:
            return
        event.discord_event_id = None
        event.discord_pushed_hash = None
        event.discord_seen_hash = None
        if event.status == "scheduled":
            event.status = "cancelled"
        await self.update(event, auto_commit=True)

    async def delete_tombstone(self, event_id: int) -> None:
        """The bot deleted this event in Discord; drop the tombstone row. Idempotent."""
        session = self.repository.session
        tombstone = (
            await session.execute(
                select(DiscordEventTombstone).where(DiscordEventTombstone.discord_event_id == event_id)
            )
        ).scalar_one_or_none()
        if tombstone is None:
            return
        await session.delete(tombstone)
        await session.commit()

    async def reconcile(self, data: DiscordEventReconcile) -> None:
        """Apply every listed event, then treat missing linked events as deleted and drop stale tombstones."""
        session = self.repository.session
        for state in data.events:
            await self.apply_event_state(state)
        listed_ids = {state.id for state in data.events}
        linked_events = list(
            (await session.execute(select(GuildEvent).where(GuildEvent.discord_event_id.is_not(None)))).scalars().all()
        )
        for event in linked_events:
            if event.discord_event_id not in listed_ids:
                await self.handle_deleted_event(event.discord_event_id)
        tombstones = list((await session.execute(select(DiscordEventTombstone))).scalars().all())
        for tombstone in tombstones:
            if tombstone.discord_event_id not in listed_ids:
                await session.delete(tombstone)
        await session.commit()

    async def _adopt_or_create(self, state: DiscordEventState) -> GuildEvent | None:
        """Link an unlinked event via the footer's link, ignore a copy of an already-linked event, or create one."""
        linked_id = _extract_linked_event_id(state.description)
        if linked_id is not None:
            candidate = await self.get_one_or_none(id=linked_id)
            if candidate is not None:
                if candidate.discord_event_id is not None:
                    return None
                candidate.discord_event_id = state.id
                return await self.update(candidate, auto_commit=True)
        if state.status in _ENDED_IN_DISCORD:
            return None
        event = GuildEvent(
            kind=EventKind.OTHER.value,
            title=state.name,
            location=state.location or "",
            starts_at=state.starts_at,
            ends_at=state.ends_at,
            size=None,
            status="scheduled",
            notes=_strip_footer(state.description),
            discord_event_id=state.id,
        )
        return await self.create(event, auto_commit=True)

    async def _tombstone(self, event_id: int) -> None:
        session = self.repository.session
        existing = (
            await session.execute(
                select(DiscordEventTombstone).where(DiscordEventTombstone.discord_event_id == event_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(DiscordEventTombstone(discord_event_id=event_id))
            await session.commit()
