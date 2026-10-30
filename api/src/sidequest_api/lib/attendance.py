"""Shared attendance semantics: who actually came to an event.

Single source of truth for Heroes stats, badges, and EP (see ``local://gm-console-contract.md`` siblings), plus the
attendance report in the GM console. Both conditions assume the query already joins ``EventSignup`` to
``GuildEvent`` (``EventSignup.event_id == GuildEvent.id``); they reference columns on both without re-joining, and
can be used either as ``.where()`` filters or selected directly as boolean columns (``select(attended_condition())``).
"""

from datetime import UTC, date, datetime

from sqlalchemy import ColumnElement, and_, or_

from sidequest_common.models import EventSignup, GuildEvent

SEASON_START = date(2026, 11, 4)
"""WoW: Forever launch day; the guild's "this season" attendance range starts here."""

VOICE_PRESENT_THRESHOLD_MINUTES = 30
"""Minutes in voice during an event's window at or above which the attendance screen pre-ticks "Came"."""


def attended_condition(*, now: datetime | None = None) -> ColumnElement[bool]:
    """Whether a sign-up counts as "came".

    True when the event started in the past, isn't cancelled, and either attendance was taken and the sign-up was
    explicitly marked ``attended``, or attendance was never taken and the sign-up's status is still ``signed`` (the
    pre-attendance-tracking default: a scheduled sign-up counted as attendance).
    """
    reference = now or datetime.now(UTC)
    return and_(
        GuildEvent.starts_at < reference,
        GuildEvent.status != "cancelled",
        or_(
            and_(GuildEvent.attendance_taken_at.is_not(None), EventSignup.attended.is_(True)),
            and_(GuildEvent.attendance_taken_at.is_(None), EventSignup.status == "signed"),
        ),
    )


def no_show_condition() -> ColumnElement[bool]:
    """Whether a sign-up is a confirmed no-show.

    Attendance was taken, the sign-up's status was ``signed``, and an officer marked it not attended.
    """
    return and_(
        GuildEvent.attendance_taken_at.is_not(None),
        EventSignup.status == "signed",
        EventSignup.attended.is_(False),
    )
