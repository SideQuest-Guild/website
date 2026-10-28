"""Fixtures for member-hub tests: a configured app with a mocked Discord transport, and a login helper.

Separate from the root ``tests/conftest.py`` (bot-facing API key client) so member-hub tests don't need Discord
OAuth configured for every other test in the suite.
"""

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from litestar.testing import AsyncTestClient

from sidequest_api.app import create_app
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import GUILD_ID, TEST_API_KEY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

OFFICER_ROLE_ID = 999_111
MEMBER_SESSION_SECRET = "a" * 32


def _discord_transport(discord_state: dict) -> httpx.MockTransport:
    """Fakes the three Discord endpoints the OAuth flow calls, driven by the mutable ``discord_state`` dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "test-access-token"})
        if path.endswith("/users/@me"):
            return httpx.Response(200, json=discord_state["user"])
        if path.endswith("/member"):
            guild_member = discord_state["guild_member"]
            if guild_member is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json=guild_member)
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.MockTransport(handler)


@pytest.fixture
def discord_state() -> dict:
    """Mutable holder the test updates before calling ``login_as``; read by the mocked Discord transport."""
    return {"user": None, "guild_member": None}


def _battlenet_transport(battlenet_state: dict) -> httpx.MockTransport:
    """Fakes Battle.net's ``/token`` and ``/userinfo``; records the token request for credential checks."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            battlenet_state["token_request"] = request
            return httpx.Response(200, json={"access_token": "bnet-access-token"})
        if request.url.path == "/userinfo":
            return httpx.Response(200, json=battlenet_state["user"])
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


@pytest.fixture
def battlenet_state() -> dict:
    """Mutable holder for the Battle.net account the mocked ``/userinfo`` returns."""
    return {"user": {"sub": "1", "id": 1, "battletag": "Tester#1111"}, "token_request": None}


@pytest.fixture
def member_web_settings() -> WebSettings:
    """Discord OAuth configured, with one officer role (``OFFICER_ROLE_ID``)."""
    return WebSettings(
        DISCORD_CLIENT_ID="test-client-id",
        DISCORD_CLIENT_SECRET="test-client-secret",
        BATTLENET_CLIENT_ID="bnet-client-id",
        BATTLENET_CLIENT_SECRET="bnet-client-secret",
        SESSION_SECRET=MEMBER_SESSION_SECRET,
        GUILD_ID=GUILD_ID,
        OFFICER_ROLE_IDS=[OFFICER_ROLE_ID],
        COOKIE_SECURE=False,
    )


@pytest.fixture
def member_app(
    database_url: str, member_web_settings: WebSettings, discord_state: dict, battlenet_state: dict
) -> Litestar:
    """App with Discord OAuth and Battle.net configured, both behind mocked transports."""
    return create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        member_web_settings,
        discord_transport=_discord_transport(discord_state),
        battlenet_transport=_battlenet_transport(battlenet_state),
    )


@pytest.fixture
async def member_client(member_app: Litestar) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """HTTP client for the member-hub app, cookies persisted across requests like a browser."""
    async with AsyncTestClient(app=member_app) as client:
        yield client


async def login_as(
    client: AsyncTestClient[Litestar],
    discord_state: dict,
    *,
    discord_id: int,
    username: str = "tester",
    is_guild_member: bool = True,
    roles: list[int] | None = None,
    next_path: str | None = None,
) -> httpx.Response:
    """Drive the full OAuth login flow for a fake Discord user; returns the callback's redirect response."""
    discord_state["user"] = {"id": str(discord_id), "username": username, "global_name": None, "avatar": None}
    discord_state["guild_member"] = (
        {"nick": None, "roles": [str(role_id) for role_id in (roles or [])]} if is_guild_member else None
    )
    params = {"next": next_path} if next_path else {}
    login_response = await client.get("/auth/discord/login", params=params, follow_redirects=False)
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    return await client.get(
        "/auth/discord/callback", params={"code": "fake-code", "state": state}, follow_redirects=False
    )


async def link_battlenet(client: AsyncTestClient[Litestar], battlenet_state: dict, *, account_id: int, battletag: str):
    """Drive the Battle.net link flow for the signed-in member; returns the callback's redirect response."""
    battlenet_state["user"] = {"sub": str(account_id), "id": account_id, "battletag": battletag}
    start = await client.get("/auth/battlenet/link", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return await client.get(
        "/auth/battlenet/callback", params={"code": "bnet-code", "state": state}, follow_redirects=False
    )
