"""Safety guard for Discord role grants/removals made by MCP tools.

Ports ``grant_block_reason`` from the bot
(``SideQuest-Guild/bot``'s ``sidequest_bot/lib/roles.py``) to work against raw Discord REST JSON (``GET
/guilds/{id}/roles`` role objects and the bot's own guild-member roles) instead of ``discord.py`` objects, since
the API never opens a gateway connection.
"""

from typing import Any

PERMISSION_BITS: dict[str, int] = {
    "create_instant_invite": 0,
    "kick_members": 1,
    "ban_members": 2,
    "administrator": 3,
    "manage_channels": 4,
    "manage_guild": 5,
    "add_reactions": 6,
    "view_audit_log": 7,
    "priority_speaker": 8,
    "stream": 9,
    "view_channel": 10,
    "send_messages": 11,
    "send_tts_messages": 12,
    "manage_messages": 13,
    "embed_links": 14,
    "attach_files": 15,
    "read_message_history": 16,
    "mention_everyone": 17,
    "use_external_emojis": 18,
    "view_guild_insights": 19,
    "connect": 20,
    "speak": 21,
    "mute_members": 22,
    "deafen_members": 23,
    "move_members": 24,
    "use_vad": 25,
    "change_nickname": 26,
    "manage_nicknames": 27,
    "manage_roles": 28,
    "manage_webhooks": 29,
    "manage_expressions": 30,
    "use_application_commands": 31,
    "request_to_speak": 32,
    "manage_events": 33,
    "manage_threads": 34,
    "create_public_threads": 35,
    "create_private_threads": 36,
    "use_external_stickers": 37,
    "send_messages_in_threads": 38,
    "use_embedded_activities": 39,
    "moderate_members": 40,
    "view_creator_monetization_analytics": 41,
    "use_soundboard": 42,
    "create_guild_expressions": 43,
    "create_events": 44,
    "use_external_sounds": 45,
    "send_voice_messages": 46,
}
"""Discord permission flag bit positions (https://discord.com/developers/docs/topics/permissions)."""

DANGEROUS_PERMISSION_NAMES = (
    "administrator",
    "ban_members",
    "kick_members",
    "manage_channels",
    "manage_events",
    "manage_expressions",
    "manage_guild",
    "manage_messages",
    "manage_nicknames",
    "manage_roles",
    "manage_threads",
    "manage_webhooks",
    "mention_everyone",
    "moderate_members",
    "mute_members",
    "deafen_members",
    "move_members",
    "view_audit_log",
)
"""Permissions a role must not carry if an MCP tool grants it; mirrors the bot's ``DANGEROUS_PERMISSIONS``."""


def dangerous_permission_names(permissions: int) -> list[str]:
    """Names of the dangerous permissions set in the ``permissions`` bitfield, sorted."""
    return sorted(name for name in DANGEROUS_PERMISSION_NAMES if permissions & (1 << PERMISSION_BITS[name]))


def bot_top_role_position(guild_roles: list[dict[str, Any]], bot_role_ids: list[str]) -> int:
    """The highest ``position`` among the roles in ``bot_role_ids`` (0 if the bot holds no roles)."""
    bot_role_id_set = set(bot_role_ids)
    positions = [int(role["position"]) for role in guild_roles if role["id"] in bot_role_id_set]
    return max(positions, default=0)


def grant_block_reason(role: dict[str, Any], *, guild_id: str, bot_top_position: int) -> str | None:
    """Why an MCP tool must not grant/remove ``role``, or ``None`` if it may.

    ``role`` is a Discord REST role object. Blocks the ``@everyone`` role, managed (integration) roles, roles at or
    above the bot's highest role (Discord would reject the change anyway), and roles carrying any dangerous
    permission.
    """
    if role["id"] == guild_id:
        return "@everyone can't be granted or removed."
    if role.get("managed"):
        return f'"{role["name"]}" is managed by an integration and can\'t be changed.'
    if int(role["position"]) >= bot_top_position:
        return f"\"{role['name']}\" is at or above the bot's highest role; move the bot's role above it first."
    if risky := dangerous_permission_names(int(role["permissions"])):
        return f'"{role["name"]}" has moderator/admin permissions ({", ".join(risky)}), so it can\'t be changed.'
    return None
