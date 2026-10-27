from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from tests.unit.api.conftest import login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_login_is_503_when_discord_oauth_is_not_configured(client: AsyncTestClient) -> None:
    """``client`` (root conftest) builds the app without ``web_settings``, so OAuth defaults to unconfigured."""
    response = await client.get("/auth/discord/login", follow_redirects=False)
    assert response.status_code == 503
    assert response.json()["detail"] == "Discord login is not configured"


async def test_callback_with_mismatched_state_is_rejected(member_client: AsyncTestClient) -> None:
    response = await member_client.get(
        "/auth/discord/callback", params={"code": "whatever", "state": "not-the-real-state"}, follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/account/?error=state"


async def test_callback_with_no_prior_login_is_rejected(member_client: AsyncTestClient) -> None:
    """No ``oauth_state`` in the session at all (never visited ``/auth/discord/login``)."""
    response = await member_client.get(
        "/auth/discord/callback", params={"code": "whatever", "state": "anything"}, follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/account/?error=state"


async def test_absolute_url_next_is_rejected_falls_back_to_account(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    response = await login_as(member_client, discord_state, discord_id=1001, next_path="https://evil.example.com/steal")
    assert response.status_code == 302
    assert response.headers["location"] == "/account/"


async def test_protocol_relative_next_is_rejected_falls_back_to_account(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    response = await login_as(member_client, discord_state, discord_id=1002, next_path="//evil.example.com/steal")
    assert response.status_code == 302
    assert response.headers["location"] == "/account/"


async def test_next_that_browsers_normalize_to_another_host_is_rejected(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    """Browsers strip tab/newline and read ``\\`` as ``/``, turning these into ``//evil.example.com``."""
    for discord_id, next_path in enumerate(
        ["/\t/evil.example.com", "/\n/evil.example.com", "/\\evil.example.com"], 1010
    ):
        response = await login_as(member_client, discord_state, discord_id=discord_id, next_path=next_path)
        assert response.status_code == 302
        assert response.headers["location"] == "/account/"


async def test_valid_same_site_next_is_honored(member_client: AsyncTestClient, discord_state: dict) -> None:
    response = await login_as(member_client, discord_state, discord_id=1003, next_path="/raids/")
    assert response.status_code == 302
    assert response.headers["location"] == "/raids/"


async def test_login_rejects_next_without_leading_slash(member_client: AsyncTestClient, discord_state: dict) -> None:
    """A bare ``next`` with no leading slash isn't a valid same-site path either."""
    login_response = await member_client.get(
        "/auth/discord/login", params={"next": "evil.example.com"}, follow_redirects=False
    )
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    discord_state["user"] = {"id": "1004", "username": "tester", "global_name": None, "avatar": None}
    discord_state["guild_member"] = {"nick": None, "roles": []}
    callback_response = await member_client.get(
        "/auth/discord/callback", params={"code": "fake-code", "state": state}, follow_redirects=False
    )
    assert callback_response.headers["location"] == "/account/"


async def test_successful_login_sets_session_and_me_reflects_it(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=1005, username="questgiver", roles=[])
    me = await member_client.get("/api/me")
    assert me.status_code == 200
    body = me.json()
    assert body["discord_id"] == "1005"
    assert body["username"] == "questgiver"
    assert body["is_guild_member"] is True
    assert body["is_officer"] is False


async def test_logout_clears_session(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=1006)
    logout_response = await member_client.post("/auth/logout")
    assert logout_response.status_code == 204
    me = await member_client.get("/api/me")
    assert me.status_code == 401


async def test_me_without_session_is_401(member_client: AsyncTestClient) -> None:
    response = await member_client.get("/api/me")
    assert response.status_code == 401
