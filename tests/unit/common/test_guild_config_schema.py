"""The bot can roll out before the API: it must read guild config from the previous release."""

from sidequest_common.schemas import GuildConfigSchema

# A config response from the release before link roles existed.
PREVIOUS_RELEASE_CONFIG = {
    "guild_id": 1564671275316543508,
    "log_channel_id": None,
    "welcome_channel_id": None,
    "welcome_message": "Welcome {mention}!",
    "auto_role_id": None,
    "leveling_enabled": True,
    "level_up_channel_id": None,
    "level_up_message": "GG {mention}, level {level}!",
    "xp_min": 15,
    "xp_max": 25,
    "xp_cooldown_seconds": 60,
    "level_roles_stack": True,
    "no_xp_channel_ids": [],
    "no_xp_role_ids": [],
    "automod_enabled": True,
    "automod_block_invites": True,
    "automod_block_links": False,
    "automod_max_mentions": 5,
    "automod_spam_messages": 5,
    "automod_spam_seconds": 5,
    "automod_timeout_seconds": 300,
    "automod_exempt_role_ids": [],
    "automod_exempt_channel_ids": [],
}


def test_reads_config_without_link_role_ids() -> None:
    config = GuildConfigSchema.model_validate(PREVIOUS_RELEASE_CONFIG)
    assert config.linked_role_id is None
    assert config.battlenet_role_id is None
    assert config.gate_role_id is None
