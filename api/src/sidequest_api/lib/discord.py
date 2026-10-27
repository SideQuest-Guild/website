"""Discord OAuth2 login + REST lookups for the member hub (not the bot's gateway connection).

The HTTP client is request-scoped and reads its transport from ``state[DISCORD_TRANSPORT_STATE_KEY]`` so tests can
inject ``httpx.MockTransport`` instead of calling the real Discord API (``create_app(discord_transport=...)``).
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
