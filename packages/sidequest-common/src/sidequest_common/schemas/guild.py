"""Guild configuration schemas."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GuildConfigSchema(BaseModel):
    """Full guild configuration as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    guild_id: int

    log_channel_id: int | None

    welcome_channel_id: int | None
    welcome_message: str
    auto_role_id: int | None
    # Defaulted so a bot rolled out before the API (deploys aren't ordered) can still read the config.
    linked_role_id: int | None = None
    battlenet_role_id: int | None = None
    gate_role_id: int | None = None
    roster_role_id: int | None = None
    events_forum_channel_id: int | None = None

    leveling_enabled: bool
    level_up_channel_id: int | None
    level_up_message: str
    xp_min: int
    xp_max: int
    xp_cooldown_seconds: int
    level_roles_stack: bool
    no_xp_channel_ids: list[int]
    no_xp_role_ids: list[int]

    automod_enabled: bool
    automod_block_invites: bool
    automod_block_links: bool
    automod_max_mentions: int
    automod_spam_messages: int
    automod_spam_seconds: int
    automod_timeout_seconds: int
    automod_exempt_role_ids: list[int]
    automod_exempt_channel_ids: list[int]

    signup_notice_channel_id: int | None = None

    weekly_board_channel_id: int | None = None
    weekly_board_last_week: str | None = None

    away_role_id: int | None = None

    badge_channel_id: int | None = None
    badge_role_ids: dict[str, int] = Field(default_factory=dict)


class GuildConfigUpdate(BaseModel):
    """Partial update. Only fields present in the request body change (``exclude_unset``).

    Send ``null`` to clear an optional channel/role.
    """

    log_channel_id: int | None = None

    welcome_channel_id: int | None = None
    welcome_message: str | None = Field(default=None, min_length=1, max_length=2000)
    auto_role_id: int | None = None
    linked_role_id: int | None = None
    battlenet_role_id: int | None = None
    gate_role_id: int | None = None
    roster_role_id: int | None = None
    events_forum_channel_id: int | None = None

    leveling_enabled: bool | None = None
    level_up_channel_id: int | None = None
    level_up_message: str | None = Field(default=None, min_length=1, max_length=2000)
    xp_min: int | None = Field(default=None, ge=0, le=1000)
    xp_max: int | None = Field(default=None, ge=0, le=1000)
    xp_cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)
    level_roles_stack: bool | None = None
    no_xp_channel_ids: list[int] | None = None
    no_xp_role_ids: list[int] | None = None

    automod_enabled: bool | None = None
    automod_block_invites: bool | None = None
    automod_block_links: bool | None = None
    automod_max_mentions: int | None = Field(default=None, ge=0, le=100)
    automod_spam_messages: int | None = Field(default=None, ge=0, le=100)
    automod_spam_seconds: int | None = Field(default=None, ge=1, le=600)
    automod_timeout_seconds: int | None = Field(default=None, ge=0, le=2_419_200)
    automod_exempt_role_ids: list[int] | None = None
    automod_exempt_channel_ids: list[int] | None = None

    signup_notice_channel_id: int | None = None

    weekly_board_channel_id: int | None = None
    weekly_board_last_week: str | None = None

    away_role_id: int | None = None

    badge_channel_id: int | None = None
    badge_role_ids: dict[str, int] | None = None

    @model_validator(mode="after")
    def _xp_range(self) -> GuildConfigUpdate:
        if self.xp_min is not None and self.xp_max is not None and self.xp_min > self.xp_max:
            msg = "xp_min must be <= xp_max"
            raise ValueError(msg)
        return self
