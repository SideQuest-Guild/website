"""Discord OAuth2 login + bot REST lookups for the member hub and MCP tools (not the bot's gateway connection).

The HTTP client is request-scoped and reads its transport from ``state[DISCORD_TRANSPORT_STATE_KEY]`` so tests can
inject ``httpx.MockTransport`` instead of calling the real Discord API (``create_app(discord_transport=...)``).
``fetch_*``/``exchange_code`` authenticate as the signed-in user (OAuth2 access token); the ``bot_*`` functions
below authenticate as the guild bot (``DiscordSettings.TOKEN``), used by MCP tools to read/write Discord directly.
"""

from collections.abc import AsyncIterator  # noqa: TC003 - provide_discord_client is a Litestar DI target
from typing import Any
from urllib.parse import urlencode

import httpx
from litestar.datastructures import State  # noqa: TC002 - provide_discord_client is a Litestar DI target

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
OAUTH_SCOPES = "identify guilds.members.read"
DISCORD_TRANSPORT_STATE_KEY = "discord_transport"


class DiscordOAuthError(Exception):
    """The OAuth code/token/user exchange failed. ``code`` is a short code for the ``?error=`` redirect."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Discord's ``/oauth2/authorize`` URL for the authorization-code flow."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": OAUTH_SCOPES,
        "state": state,
    }
    return f"{DISCORD_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(
    client: httpx.AsyncClient, *, client_id: str, client_secret: str, redirect_uri: str, code: str
) -> str:
    """Exchange an authorization code for an access token. Raises :class:`DiscordOAuthError` on failure."""
    try:
        response = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
    except httpx.TransportError as exc:
        msg = "Could not reach Discord"
        error_code = "discord_unreachable"
        raise DiscordOAuthError(error_code, msg) from exc
    if response.status_code != httpx.codes.OK:
        msg = f"Token exchange failed: {response.status_code}"
        error_code = "token_exchange_failed"
        raise DiscordOAuthError(error_code, msg)
    token = response.json().get("access_token")
    if not token:
        msg = "Discord did not return an access token"
        error_code = "token_exchange_failed"
        raise DiscordOAuthError(error_code, msg)
    return str(token)


async def fetch_current_user(client: httpx.AsyncClient, access_token: str) -> dict[str, Any]:
    """``GET /users/@me``."""
    response = await client.get("/users/@me", headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code != httpx.codes.OK:
        msg = f"Could not fetch Discord user: {response.status_code}"
        error_code = "user_fetch_failed"
        raise DiscordOAuthError(error_code, msg)
    result: dict[str, Any] = response.json()
    return result


async def fetch_guild_member(client: httpx.AsyncClient, access_token: str, guild_id: int) -> dict[str, Any] | None:
    """``GET /users/@me/guilds/{guild_id}/member``. ``None`` if the user isn't a member of the guild (404)."""
    response = await client.get(
        f"/users/@me/guilds/{guild_id}/member", headers={"Authorization": f"Bearer {access_token}"}
    )
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    if response.status_code != httpx.codes.OK:
        msg = f"Could not fetch guild membership: {response.status_code}"
        error_code = "guild_member_fetch_failed"
        raise DiscordOAuthError(error_code, msg)
    result: dict[str, Any] = response.json()
    return result


def avatar_url(discord_id: int, avatar_hash: str | None) -> str:
    """Discord CDN avatar URL; falls back to Discord's default avatar if the user has none set."""
    if avatar_hash:
        ext = "gif" if avatar_hash.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.{ext}"
    index = (discord_id >> 22) % 6
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


async def provide_discord_client(state: State) -> AsyncIterator[httpx.AsyncClient]:
    """Per-request Discord HTTP client. Tests set ``state[DISCORD_TRANSPORT_STATE_KEY]`` to a mock transport."""
    transport = state.get(DISCORD_TRANSPORT_STATE_KEY)
    async with httpx.AsyncClient(base_url=DISCORD_API_BASE, timeout=10.0, transport=transport) as client:
        yield client


class DiscordApiError(Exception):
    """A bot-authenticated Discord REST call failed. ``status_code`` is Discord's HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _bot_headers(bot_token: str) -> dict[str, str]:
    return {"Authorization": f"Bot {bot_token}"}


async def _bot_request(
    client: httpx.AsyncClient, bot_token: str, method: str, path: str, **kwargs: Any
) -> httpx.Response:
    response = await client.request(method, path, headers=_bot_headers(bot_token), **kwargs)
    if response.status_code >= httpx.codes.BAD_REQUEST:
        msg = f"Discord {method} {path} failed: {response.status_code} {response.text}"
        raise DiscordApiError(response.status_code, msg)
    return response


async def bot_get_guild_member(
    client: httpx.AsyncClient, bot_token: str, guild_id: int, user_id: int | str
) -> dict[str, Any]:
    """``GET /guilds/{guild_id}/members/{user_id}`` (bot auth). ``user_id="@me"`` gets the bot's own member."""
    response = await _bot_request(client, bot_token, "GET", f"/guilds/{guild_id}/members/{user_id}")
    result: dict[str, Any] = response.json()
    return result


async def bot_list_guild_roles(client: httpx.AsyncClient, bot_token: str, guild_id: int) -> list[dict[str, Any]]:
    """``GET /guilds/{guild_id}/roles`` (bot auth): every role, with permissions/position/managed."""
    response = await _bot_request(client, bot_token, "GET", f"/guilds/{guild_id}/roles")
    result: list[dict[str, Any]] = response.json()
    return result


async def bot_list_guild_channels(client: httpx.AsyncClient, bot_token: str, guild_id: int) -> list[dict[str, Any]]:
    """``GET /guilds/{guild_id}/channels`` (bot auth): every channel and category."""
    response = await _bot_request(client, bot_token, "GET", f"/guilds/{guild_id}/channels")
    result: list[dict[str, Any]] = response.json()
    return result


async def bot_get_channel_messages(
    client: httpx.AsyncClient, bot_token: str, channel_id: int, *, limit: int
) -> list[dict[str, Any]]:
    """``GET /channels/{channel_id}/messages`` (bot auth), newest first, capped at ``limit``."""
    response = await _bot_request(client, bot_token, "GET", f"/channels/{channel_id}/messages", params={"limit": limit})
    result: list[dict[str, Any]] = response.json()
    return result


async def bot_send_channel_message(
    client: httpx.AsyncClient,
    bot_token: str,
    channel_id: int,
    *,
    content: str | None = None,
    embed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``POST /channels/{channel_id}/messages`` (bot auth).

    Mentions are limited to users named in ``content`` (``@everyone``/``@here``/role mentions never ping,
    matching the bot's own posting rules).
    """
    payload: dict[str, Any] = {"allowed_mentions": {"parse": ["users"]}}
    if content is not None:
        payload["content"] = content
    if embed is not None:
        payload["embeds"] = [embed]
    response = await _bot_request(client, bot_token, "POST", f"/channels/{channel_id}/messages", json=payload)
    result: dict[str, Any] = response.json()
    return result


async def bot_edit_channel_message(
    client: httpx.AsyncClient, bot_token: str, channel_id: int, message_id: int, *, content: str
) -> dict[str, Any]:
    """``PATCH /channels/{channel_id}/messages/{message_id}`` (bot auth)."""
    response = await _bot_request(
        client,
        bot_token,
        "PATCH",
        f"/channels/{channel_id}/messages/{message_id}",
        json={"content": content, "allowed_mentions": {"parse": ["users"]}},
    )
    result: dict[str, Any] = response.json()
    return result


async def bot_get_guild_audit_log(
    client: httpx.AsyncClient, bot_token: str, guild_id: int, *, limit: int
) -> list[dict[str, Any]]:
    """``GET /guilds/{guild_id}/audit-logs`` (bot auth), newest first, capped at ``limit``."""
    response = await _bot_request(client, bot_token, "GET", f"/guilds/{guild_id}/audit-logs", params={"limit": limit})
    result: dict[str, Any] = response.json()
    entries: list[dict[str, Any]] = result.get("audit_log_entries", [])
    return entries


async def bot_add_guild_member_role(
    client: httpx.AsyncClient, bot_token: str, guild_id: int, user_id: int, role_id: int
) -> None:
    """``PUT /guilds/{guild_id}/members/{user_id}/roles/{role_id}`` (bot auth)."""
    await _bot_request(client, bot_token, "PUT", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}")


async def bot_remove_guild_member_role(
    client: httpx.AsyncClient, bot_token: str, guild_id: int, user_id: int, role_id: int
) -> None:
    """``DELETE /guilds/{guild_id}/members/{user_id}/roles/{role_id}`` (bot auth)."""
    await _bot_request(client, bot_token, "DELETE", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}")
