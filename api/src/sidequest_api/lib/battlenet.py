"""Battle.net OAuth2 for linking a member's Blizzard account (BattleTag) to their Discord-backed profile.

Requests ``openid`` (proves account ownership, yields the account id and BattleTag via ``/userinfo``) and
``wow.profile`` (lets the site read the account's WoW Forever characters via ``AsyncAccount.profile()``, a
community-probed, undocumented endpoint — Blizzard has not published a Forever profile API). A failure to read
the profile never blocks linking: the BattleTag proof still succeeds, just without character ids to auto-link
against. ``oauth.battle.net`` serves the US region.
"""

from collections.abc import AsyncIterator  # noqa: TC003 - provide_battlenet_client is a Litestar DI target
from urllib.parse import urlencode

import httpx
from litestar.datastructures import State  # noqa: TC002 - provide_battlenet_client is a Litestar DI target
from wow import AsyncClient, WowError

BATTLENET_OAUTH_BASE = "https://oauth.battle.net"
BATTLENET_SCOPES = "openid wow.profile"
BATTLENET_TRANSPORT_STATE_KEY = "battlenet_transport"


class BattleNetOAuthError(Exception):
    """The Battle.net code/token/userinfo exchange failed. ``code`` is a short code for the ``?error=`` redirect."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Battle.net's ``/authorize`` URL for the authorization-code flow."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": BATTLENET_SCOPES,
        "state": state,
    }
    return f"{BATTLENET_OAUTH_BASE}/authorize?{urlencode(params)}"


async def exchange_code(
    client: httpx.AsyncClient, *, client_id: str, client_secret: str, redirect_uri: str, code: str
) -> str:
    """Exchange an authorization code for an access token (client credentials via HTTP Basic)."""
    try:
        response = await client.post(
            "/token",
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
            auth=(client_id, client_secret),
        )
    except httpx.TransportError as exc:
        msg = "Could not reach Battle.net"
        error_code = "battlenet_unreachable"
        raise BattleNetOAuthError(error_code, msg) from exc
    token = response.json().get("access_token") if response.status_code == httpx.codes.OK else None
    if not token:
        msg = f"Battle.net token exchange failed: {response.status_code}"
        error_code = "battlenet_failed"
        raise BattleNetOAuthError(error_code, msg)
    return str(token)


async def fetch_userinfo(client: httpx.AsyncClient, access_token: str) -> tuple[int, str]:
    """``GET /userinfo``: the Battle.net account id and BattleTag."""
    try:
        response = await client.get("/userinfo", headers={"Authorization": f"Bearer {access_token}"})
    except httpx.TransportError as exc:
        msg = "Could not reach Battle.net"
        error_code = "battlenet_unreachable"
        raise BattleNetOAuthError(error_code, msg) from exc
    body = response.json() if response.status_code == httpx.codes.OK else {}
    account_id, battletag = body.get("id"), body.get("battletag")
    if account_id is None or not battletag:
        msg = f"Battle.net userinfo failed: {response.status_code}"
        error_code = "battlenet_failed"
        raise BattleNetOAuthError(error_code, msg)
    return int(account_id), str(battletag)


async def provide_battlenet_client(state: State) -> AsyncIterator[httpx.AsyncClient]:
    """Per-request Battle.net HTTP client. Tests set ``state[BATTLENET_TRANSPORT_STATE_KEY]`` to a mock transport."""
    transport = state.get(BATTLENET_TRANSPORT_STATE_KEY)
    async with httpx.AsyncClient(base_url=BATTLENET_OAUTH_BASE, timeout=10.0, transport=transport) as client:
        yield client


async def fetch_account_character_ids(game_data: AsyncClient, access_token: str) -> list[int]:
    """The Battle.net ids of every WoW Forever character on the account that owns ``access_token``.

    Uses the app's game-data client with the user's token swapped in (``wow.profile`` scope), so it needs no
    separate HTTP client or region handling. Best-effort: returns an empty list rather than raising if Battle.net
    fails or the undocumented profile shape doesn't parse, so a flaky profile read never blocks linking.
    """
    try:
        profile = await game_data.with_options(access_token=access_token).account.profile()
    except WowError:
        return []
    return [character.id for account in profile.wow_accounts for character in account.characters]
