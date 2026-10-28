import base64
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from tests.unit.api.conftest import OFFICER_ROLE_ID, link_battlenet, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_link_requires_discord_sign_in_first(member_client: AsyncTestClient) -> None:
    response = await member_client.get("/auth/battlenet/link", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/account/?error=signin_first"


async def test_link_redirect_goes_to_battlenet_with_openid_only(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=5001)
    response = await member_client.get("/auth/battlenet/link", follow_redirects=False)
    location = urlparse(response.headers["location"])
    query = parse_qs(location.query)
    assert (location.scheme, location.netloc, location.path) == ("https", "oauth.battle.net", "/authorize")
    assert query["scope"] == ["openid"]
    assert query["redirect_uri"] == ["http://localhost:8000/auth/battlenet/callback"]


async def test_linking_shows_battletag_on_me_and_sends_basic_auth(
    member_client: AsyncTestClient, discord_state: dict, battlenet_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=5002)
    response = await link_battlenet(member_client, battlenet_state, account_id=77, battletag="Coffee#1234")
    assert response.status_code == 302
    assert response.headers["location"] == "/account/"

    me = await member_client.get("/api/me")
    assert me.json()["battletag"] == "Coffee#1234"
    token_request = battlenet_state["token_request"]
    expected = base64.b64encode(b"bnet-client-id:bnet-client-secret").decode()
    assert token_request.headers["authorization"] == f"Basic {expected}"


async def test_callback_with_mismatched_state_does_not_link(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=5003)
    await member_client.get("/auth/battlenet/link", follow_redirects=False)
    response = await member_client.get(
        "/auth/battlenet/callback", params={"code": "x", "state": "forged"}, follow_redirects=False
    )
    assert response.headers["location"] == "/account/?error=state"
    assert (await member_client.get("/api/me")).json()["battletag"] is None


async def test_declining_on_battlenet_reports_denied(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=5004)
    start = await member_client.get("/auth/battlenet/link", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    response = await member_client.get(
        "/auth/battlenet/callback", params={"error": "access_denied", "state": state}, follow_redirects=False
    )
    assert response.headers["location"] == "/account/?error=battlenet_denied"


async def test_one_battlenet_account_cannot_vouch_for_two_members(
    member_client: AsyncTestClient, discord_state: dict, battlenet_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=5005)
    await link_battlenet(member_client, battlenet_state, account_id=88, battletag="Shared#0001")

    await login_as(member_client, discord_state, discord_id=5006)
    response = await link_battlenet(member_client, battlenet_state, account_id=88, battletag="Shared#0001")
    assert response.headers["location"] == "/account/?error=battlenet_taken"
    assert (await member_client.get("/api/me")).json()["battletag"] is None


async def test_unlink_clears_battletag(
    member_client: AsyncTestClient, discord_state: dict, battlenet_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=5007)
    await link_battlenet(member_client, battlenet_state, account_id=99, battletag="Gone#4242")
    assert (await member_client.post("/auth/battlenet/unlink")).status_code == 204
    assert (await member_client.get("/api/me")).json()["battletag"] is None

    # The account is free again for someone else.
    await login_as(member_client, discord_state, discord_id=5008)
    response = await link_battlenet(member_client, battlenet_state, account_id=99, battletag="Gone#4242")
    assert response.headers["location"] == "/account/"


async def test_member_list_is_officer_only_and_carries_battletags(
    member_client: AsyncTestClient, discord_state: dict, battlenet_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=5009, username="raider")
    await link_battlenet(member_client, battlenet_state, account_id=101, battletag="Raider#5555")
    assert (await member_client.get("/api/members")).status_code == 403

    await login_as(member_client, discord_state, discord_id=5010, username="officer", roles=[OFFICER_ROLE_ID])
    listing = await member_client.get("/api/members")
    assert listing.status_code == 200, listing.text
    by_name = {row["username"]: row for row in listing.json()}
    assert by_name["raider"]["battletag"] == "Raider#5555"
    assert by_name["officer"]["is_officer"] is True
