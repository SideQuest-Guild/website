"""Group voice channels: short-lived Discord voice channels members spawn from the ``#lfg`` panel.

The bot creates the channel and a ``GroupSession`` row, reports who is in it while it lives, and closes the session
(with the channel's text chat) when the channel empties. Officers read the stats; the transcript is purged after
``GROUP_TRANSCRIPT_RETENTION_DAYS``.
"""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime
from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class GroupSession(UUIDAuditBase):
    """One group voice channel's life, from the panel click to teardown.

    ``kind`` is an ``EventKind`` value from ``GROUP_KINDS``. ``event_id`` is set when the channel was opened from a
    scheduled guild event. ``peak_size`` and ``grouped_minutes`` (minutes with two or more members present) only
    ever rise; a session counts toward stats when ``peak_size >= 2`` and ``grouped_minutes >=
    COUNTED_GROUP_MINUTES``.

    ``pug_role_id`` is set for a PUG group: the temporary Discord role its invite link grants to outside players,
    allowed into this channel only. The bot deletes the role when the group ends. ``pug_minutes`` (only ever rises)
    counts minutes with at least one guild member and one of those outside players present together; a PUG group
    counts toward its creator's PUG-host badges once it reaches ``COUNTED_GROUP_MINUTES``.
    """

    __tablename__ = "group_session"
    __table_args__ = {"comment": "Group voice channels spawned from the LFG panel, bot-reported."}

    discord_channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    channel_name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str | None] = mapped_column(String(80), default=None)
    note: Mapped[str | None] = mapped_column(String(200), default=None)
    needs: Mapped[list[str]] = mapped_column(JsonB, default=list)
    cap: Mapped[int | None] = mapped_column(Integer, default=None)
    creator_discord_id: Mapped[int] = mapped_column(BigInteger, index=True)
    owner_discord_id: Mapped[int] = mapped_column(BigInteger)
    event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("guild_event.id", ondelete="SET NULL"), index=True, default=None
    )
    card_message_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    pug_role_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), index=True, default=None)
    end_reason: Mapped[str | None] = mapped_column(String(20), default=None)
    peak_size: Mapped[int] = mapped_column(Integer, default=0)
    grouped_minutes: Mapped[int] = mapped_column(Integer, default=0)
    pug_minutes: Mapped[int] = mapped_column(Integer, default=0)


class GroupSessionMember(UUIDAuditBase):
    """Minutes one Discord member spent in one group channel. Bot-reported; stored as ``max(existing, reported)``."""

    __tablename__ = "group_session_member"
    __table_args__ = (
        UniqueConstraint("session_id", "discord_id", name="uq_group_session_member_session_discord"),
        {"comment": "Minutes a Discord member spent in a group voice channel, bot-reported."},
    )

    session_id: Mapped[UUID] = mapped_column(ForeignKey("group_session.id", ondelete="CASCADE"), index=True)
    discord_id: Mapped[int] = mapped_column(BigInteger, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    minutes: Mapped[int] = mapped_column(Integer, default=0)


class GroupSessionPair(UUIDAuditBase):
    """Minutes two members spent in the same group channel together. ``discord_id_a < discord_id_b`` always."""

    __tablename__ = "group_session_pair"
    __table_args__ = (
        UniqueConstraint("session_id", "discord_id_a", "discord_id_b", name="uq_group_session_pair_session_ab"),
        {"comment": "Minutes a pair of members spent together in a group voice channel, bot-reported."},
    )

    session_id: Mapped[UUID] = mapped_column(ForeignKey("group_session.id", ondelete="CASCADE"), index=True)
    discord_id_a: Mapped[int] = mapped_column(BigInteger, index=True)
    discord_id_b: Mapped[int] = mapped_column(BigInteger, index=True)
    minutes: Mapped[int] = mapped_column(Integer, default=0)


class GroupSessionTranscript(UUIDAuditBase):
    """A closed group channel's text chat, kept for moderation and purged after the retention window.

    ``messages`` is a list of ``GroupTranscriptMessage`` dicts, oldest first.
    """

    __tablename__ = "group_session_transcript"
    __table_args__ = {"comment": "Text chat of a closed group voice channel; purged after 30 days."}

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_session.id", ondelete="CASCADE"), unique=True, index=True
    )
    messages: Mapped[list[dict[str, object]]] = mapped_column(JsonB, default=list)
