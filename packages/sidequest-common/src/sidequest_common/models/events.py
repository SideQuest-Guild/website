"""Guild events and member signups. A raid is one kind of guild event; see ``EventKind``.

``EventSeries`` is a repeating-event rule (e.g. "every Friday at 7pm"); it never shows up to members directly.
Instead the API materializes it into ordinary ``GuildEvent`` rows (its "occurrences") up to a 14-day horizon, each
with its own sign-ups and Discord event. See ``local://event-series-contract.md``.
"""

from datetime import date, datetime, time  # SQLAlchemy resolves Mapped[] annotations at runtime
from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

EVENT_KINDS = ("raid", "dungeon", "leveling", "pvp", "social", "other")
ROLE_KINDS = ("raid", "dungeon")
EVENT_STATUSES = ("scheduled", "cancelled", "completed")
SIGNUP_ROLES = ("tank", "healer", "dps")
SIGNUP_STATUSES = ("signed", "tentative", "absent")
WOW_CLASSES = (
    "warrior",
    "paladin",
    "hunter",
    "rogue",
    "priest",
    "shaman",
    "mage",
    "warlock",
    "druid",
)


class EventSeries(UUIDAuditBase):
    """A repeating guild event rule ("every Friday at 7pm"). Materializes into ``GuildEvent`` occurrences.

    ``weekdays`` is ``0`` (Monday) through ``6`` (Sunday). ``interval_weeks`` is ``1`` (every week) or ``2`` (every
    other week, anchored on ``starts_on``'s week). ``start_time`` is wall-clock time in ``timezone`` (IANA, e.g.
    ``"America/Chicago"``); occurrences convert it to UTC per-occurrence via ``zoneinfo``, so DST shifts land
    correctly. ``skipped_dates`` (ISO date strings) are occurrence dates a member deleted; they are never
    recreated. ``active`` is cleared once ``until`` has passed.
    """

    __tablename__ = "event_series"
    __table_args__ = {"comment": "Repeating guild event rules; occurrences materialize as ordinary GuildEvent rows."}

    kind: Mapped[str] = mapped_column(String(20), default="other")
    title: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text)
    size: Mapped[int | None] = mapped_column(Integer, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    weekdays: Mapped[list[int]] = mapped_column(JsonB, default=list)
    interval_weeks: Mapped[int] = mapped_column(Integer, default=1)
    start_time: Mapped[time] = mapped_column(Time)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    timezone: Mapped[str] = mapped_column(String(64))
    starts_on: Mapped[date] = mapped_column(Date)
    until: Mapped[date | None] = mapped_column(Date, default=None)
    skipped_dates: Mapped[list[str]] = mapped_column(JsonB, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    occurrences: Mapped[list["GuildEvent"]] = relationship(back_populates="series")


class GuildEvent(UUIDAuditBase):
    """One scheduled guild event, mirrored to a Discord scheduled event when the bot is running.

    ``kind`` distinguishes raids from other events (dungeon runs, leveling sessions, PvP, social hangs); only
    "role kinds" (raid, dungeon) use the character/class/role sign-up fields and the raid chart. ``location`` is
    ``""`` and ``size`` is ``None`` for events first created in Discord (Discord has neither). The ``discord_*``
    columns belong to the two-way sync: ``discord_pushed_hash`` is the hash of the last desired state the bot wrote
    to Discord, ``discord_seen_hash`` the hash of the last Discord state the bot reported. An event needs a push
    when its current desired-state hash differs from ``discord_pushed_hash``; a Discord report whose hash equals
    ``discord_seen_hash`` is our own echo and is ignored. ``series_id``/``occurrence_date`` link an occurrence back
    to the ``EventSeries`` that materialized it; ``series_detached`` is set once an officer edits or deletes that
    one occurrence, so series-wide edits stop touching it.
    """

    __tablename__ = "guild_event"
    __table_args__ = (
        UniqueConstraint("series_id", "occurrence_date", name="uq_guild_event_series_occurrence"),
        {"comment": "Scheduled guild events (raids, dungeons, leveling, pvp, social, other)."},
    )

    kind: Mapped[str] = mapped_column(String(20), default="other")
    title: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    size: Mapped[int | None] = mapped_column(Integer, default=None)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    discord_event_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, default=None)
    discord_thread_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, default=None)
    discord_pushed_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    discord_seen_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    series_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_series.id", ondelete="SET NULL"), index=True, default=None
    )
    occurrence_date: Mapped[date | None] = mapped_column(Date, default=None)
    series_detached: Mapped[bool] = mapped_column(Boolean, default=False)

    series: Mapped[EventSeries | None] = relationship(back_populates="occurrences", lazy="selectin")


class DiscordEventTombstone(UUIDAuditBase):
    """A Discord scheduled event whose guild event was deleted on the site; the bot deletes it, then this row."""

    __tablename__ = "discord_event_tombstone"
    __table_args__ = {"comment": "Discord scheduled events still to delete after their guild event was deleted."}

    discord_event_id: Mapped[int] = mapped_column(BigInteger, unique=True)


SIGNUP_ACTIVITY_ACTIONS = ("going", "maybe", "not_going", "withdrew")


class EventDiscordInterest(UUIDAuditBase):
    """One Discord user who clicked "Interested" on a guild event's linked Discord scheduled event.

    Discord -> site only: the API can't mark a Discord user interested on the site's behalf. Replaced wholesale per
    event whenever the bot reports the current interested-user list.
    """

    __tablename__ = "event_discord_interest"
    __table_args__ = (
        UniqueConstraint("event_id", "discord_id", name="uq_event_discord_interest_event_discord"),
        {"comment": "Discord users interested in a guild event's linked Discord scheduled event."},
    )

    event_id: Mapped[UUID] = mapped_column(ForeignKey("guild_event.id", ondelete="CASCADE"), index=True)
    discord_id: Mapped[int] = mapped_column(BigInteger)


class EventSignupActivity(UUIDAuditBase):
    """One sign-up status change, queued to post as a comment on the event's Discord forum thread.

    ``action`` is one of ``SIGNUP_ACTIVITY_ACTIONS``: ``going``/``maybe``/``not_going`` mirror a signup's
    ``status``, and ``withdrew`` marks a deleted signup. ``detail`` is the short "Character · Class · Role" line
    for role-kind events, else ``None``. ``posted_at`` is set once the bot acks it; rows for events with no
    Discord thread stay unposted (and are dropped by the API if older than 24h) rather than posted.
    """

    __tablename__ = "event_signup_activity"
    __table_args__ = {"comment": "Sign-up activity queued to post as forum comments on an event's Discord thread."}

    event_id: Mapped[UUID] = mapped_column(ForeignKey("guild_event.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(10))
    detail: Mapped[str | None] = mapped_column(String(200), default=None)
    posted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)


class EventSignup(UUIDAuditBase):
    """One member's signup for one guild event. ``class`` is a Python keyword, so the column is ``wow_class``.

    ``character``/``wow_class``/``role`` are nullable: only role kinds (raid, dungeon) require them.
    """

    __tablename__ = "event_signup"
    __table_args__ = (
        UniqueConstraint("event_id", "member_id", name="uq_event_signup_event_member"),
        {"comment": "Member signups for a guild event, including the officer-assigned raid chart (group/bench)."},
    )

    event_id: Mapped[UUID] = mapped_column(ForeignKey("guild_event.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id", ondelete="CASCADE"), index=True)
    character: Mapped[str | None] = mapped_column(String(24), default=None)
    wow_class: Mapped[str | None] = mapped_column(String(20), default=None)
    role: Mapped[str | None] = mapped_column(String(10), default=None)
    status: Mapped[str] = mapped_column(String(10), default="signed")
    comment: Mapped[str | None] = mapped_column(String(200), default=None)
    chart_group: Mapped[int | None] = mapped_column("chart_group", Integer, default=None)
    bench: Mapped[bool] = mapped_column(Boolean, default=False)
