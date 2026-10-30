"""RFC 5545 iCalendar feed for a member's private calendar link.

Used by ``domain/calendar`` only. Builds one ``VEVENT`` per guild event, with proper text escaping and line
folding (RFC 5545 §3.1: physical lines wrap at 75 octets, continuations lead with a single space) so the feed
validates for both Google Calendar and Apple Calendar subscriptions.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sidequest_common.schemas.events import EVENT_KIND_LABELS, EventKind

if TYPE_CHECKING:
    from sidequest_common.models import EventSignup, GuildEvent

_FOLD_LIMIT = 75
"""Maximum octets per physical content line before folding, per RFC 5545."""

_ESCAPE_RE = re.compile(r"[\\;,\n]")
_ESCAPES = {"\\": "\\\\", ";": "\\;", ",": "\\,", "\n": "\\n"}

_DEFAULT_EVENT_LENGTH = timedelta(hours=3)
"""How long an event without an explicit end counts as running, matching the bot's presence line."""

_STATUS_LABELS = {"signed": "Going", "tentative": "Maybe", "absent": "Not going"}
_ROLE_LABELS = {"tank": "Tank", "healer": "Healer", "dps": "DPS"}


def _escape(text: str) -> str:
    """Escape backslashes, semicolons, commas and newlines per RFC 5545 §3.3.11."""
    return _ESCAPE_RE.sub(lambda match: _ESCAPES[match.group()], text)


def _fold(line: str) -> str:
    """Fold ``line`` to at most 75 octets per physical line, continuations starting with a single space."""
    encoded = line.encode("utf-8")
    if len(encoded) <= _FOLD_LIMIT:
        return line
    chunks: list[bytes] = []
    start = 0
    limit = _FOLD_LIMIT
    while start < len(encoded):
        end = min(start + limit, len(encoded))
        while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:  # noqa: PLR2004 - don't split a UTF-8 sequence
            end -= 1
        chunks.append(encoded[start:end])
        start = end
        limit = _FOLD_LIMIT - 1  # continuation lines lose one octet to their leading space
    return "\r\n ".join(chunk.decode("utf-8") for chunk in chunks)


def _format_dt(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _signup_line(signup: EventSignup | None) -> str | None:
    """Example: "Going as Oakenshield · Warrior · Tank", or just the status line. ``None`` if there's no signup."""
    if signup is None:
        return None
    status_label = _STATUS_LABELS.get(signup.status, signup.status.capitalize())
    if signup.character and signup.wow_class and signup.role:
        role_label = _ROLE_LABELS.get(signup.role, signup.role.capitalize())
        return f"{status_label} as {signup.character} · {signup.wow_class.capitalize()} · {role_label}"
    return status_label


def _vevent(event: GuildEvent, signup: EventSignup | None, *, base_url: str, now: datetime) -> list[str]:
    kind_label = EVENT_KIND_LABELS.get(EventKind(event.kind), event.kind.capitalize())
    summary = f"{event.title} ({kind_label})"
    event_url = f"{base_url}/events/detail/?id={event.id}"
    description_parts = [part for part in (_signup_line(signup), event.notes, event_url) if part]
    ends_at = event.ends_at or (event.starts_at + _DEFAULT_EVENT_LENGTH)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{event.id}@sidequest-guild.com",
        f"DTSTAMP:{_format_dt(now)}",
        f"DTSTART:{_format_dt(event.starts_at)}",
        f"DTEND:{_format_dt(ends_at)}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(chr(10).join(description_parts))}",
        f"URL:{event_url}",
        f"X-SIDEQUEST-KIND:{_escape(event.kind)}",
    ]
    if signup is not None:
        lines.append(f"X-SIDEQUEST-SIGNUP:{_escape(signup.status)}")
    if event.location:
        lines.append(f"LOCATION:{_escape(event.location)}")
    if event.status == "cancelled":
        lines.append("STATUS:CANCELLED")
    lines.append("END:VEVENT")
    return [_fold(line) for line in lines]


def build_calendar_feed(
    events: list[tuple[GuildEvent, EventSignup | None]], *, base_url: str, now: datetime | None = None
) -> str:
    """The full ``.ics`` text for one member's private feed. ``events`` pairs each event with their own signup."""
    now = now or datetime.now(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SideQuest Guild//Member Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        _fold("X-WR-CALNAME:SideQuest"),
    ]
    for event, signup in events:
        lines.extend(_vevent(event, signup, base_url=base_url, now=now))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
