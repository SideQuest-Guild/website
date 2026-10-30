"""Per-guild configuration."""

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import JsonB
from sqlalchemy import BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

DEFAULT_WELCOME_MESSAGE = "Welcome to **{guild}**, {mention}! Pull up a seat by the fire, adventurer."
DEFAULT_LEVEL_UP_MESSAGE = "GG {mention}, you just advanced to level {level}!"


class GuildConfig(UUIDAuditBase):
    """Settings for one Discord guild. Created with defaults the first time the bot asks for it."""

    __tablename__ = "guild_config"
    __table_args__ = {"comment": "Per-guild bot configuration."}

    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)

    # Logging
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    # Welcome
    welcome_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    welcome_message: Mapped[str] = mapped_column(Text, default=DEFAULT_WELCOME_MESSAGE)
    auto_role_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    linked_role_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    battlenet_role_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    gate_role_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    roster_role_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    # Events
    events_forum_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    # Leveling
    leveling_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    level_up_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    level_up_message: Mapped[str] = mapped_column(Text, default=DEFAULT_LEVEL_UP_MESSAGE)
    xp_min: Mapped[int] = mapped_column(Integer, default=15)
    xp_max: Mapped[int] = mapped_column(Integer, default=25)
    xp_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    level_roles_stack: Mapped[bool] = mapped_column(Boolean, default=True)
    no_xp_channel_ids: Mapped[list[int]] = mapped_column(JsonB, default=list)
    no_xp_role_ids: Mapped[list[int]] = mapped_column(JsonB, default=list)

    # Automod
    automod_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    automod_block_invites: Mapped[bool] = mapped_column(Boolean, default=True)
    automod_block_links: Mapped[bool] = mapped_column(Boolean, default=False)
    automod_max_mentions: Mapped[int] = mapped_column(Integer, default=5)
    automod_spam_messages: Mapped[int] = mapped_column(Integer, default=5)
    automod_spam_seconds: Mapped[int] = mapped_column(Integer, default=5)
    automod_timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    automod_exempt_role_ids: Mapped[list[int]] = mapped_column(JsonB, default=list)
    automod_exempt_channel_ids: Mapped[list[int]] = mapped_column(JsonB, default=list)

    # Signup notices
    signup_notice_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    # Weekly board
    weekly_board_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    weekly_board_last_week: Mapped[str | None] = mapped_column(String(10), default=None)
    """ISO date (``YYYY-MM-DD``) of the Monday whose board was last posted; prevents double-posting."""

    # Away
    away_role_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    # Hall of Heroes badges
    badge_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    badge_role_ids: Mapped[dict[str, int]] = mapped_column(JsonB, default=dict)
    """Discord role id per badge id, created and kept by the bot's badges plugin."""

    # Guild hub announcements (v2)
    announcement_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    """Where the bot posts pending ``GuildAnnouncement`` rows queued for Discord; officers set it."""
