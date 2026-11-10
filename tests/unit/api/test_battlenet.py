import base64
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import select

from sidequest_api.app import create_app
from sidequest_common.models import BattlenetCharacter, Member, WowCharacter
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import TEST_API_KEY
from tests.unit.api.conftest import _battlenet_transport, _discord_transport, link_battlenet, login_as

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_link_requires_discord_sign_in_first(member_client: AsyncTestClient) -> None:
    response = await member_client.get("/auth/battlenet/link", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/account/?error=signin_first"


async def test_link_redirect_goes_to_battlenet_with_openid_and_profile_scope(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=5001)
    response = await member_client.get("/auth/battlenet/link", follow_redirects=False)
    location = urlparse(response.headers["location"])
    query = parse_qs(location.query)
    assert (location.scheme, location.netloc, location.path) == ("https", "oauth.battle.net", "/authorize")
    assert query["scope"] == ["openid wow.profile"]
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


def _account_profile_transport(characters: list[dict]) -> httpx.MockTransport:
    """Fakes the Battle.net account profile endpoint (``wow.profile`` scope) with one WoW account's characters."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/profile/user/wow":
            return httpx.Response(503, json={"code": 503})
        return httpx.Response(
            200,
            json={
                "_links": {"self": {"href": "https://us.api.blizzard.com/profile/user/wow"}},
                "wow_accounts": [
                    {
                        "id": 1,
                        "characters": [
                            {
                                "character": {"href": "https://us.api.blizzard.com/profile/wow/character/x"},
                                "protected_character": {
                                    "href": f"https://us.api.blizzard.com/profile/user/wow/protected-character/1-{c['id']}"
                                },
                                "name": c["name"],
                                "surname": c["surname"],
                                "id": c["id"],
                                "playable_class": {"id": 4, "name": "Rogue"},
                                "playable_race": {"id": 1, "name": "Human"},
                                "gender": {"type": "MALE", "name": "Male"},
                                "faction": {"type": "ALLIANCE", "name": "Alliance"},
                                "level": c.get("level", 60),
                            }
                            for c in characters
                        ],
                    }
                ],
            },
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def owned_characters() -> list[dict]:
    """Characters the fake account profile reports; tests fill this in before signing in."""
    return []


@pytest.fixture
async def battlenet_profile_client(
    database_url: str,
    member_web_settings: WebSettings,
    discord_state: dict,
    battlenet_state: dict,
    owned_characters: list[dict],
) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Like ``member_client``, but the account profile endpoint answers with ``owned_characters``."""
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        member_web_settings,
        discord_transport=_discord_transport(discord_state),
        battlenet_transport=_battlenet_transport(battlenet_state),
        game_data_transport=_account_profile_transport(owned_characters),
    )
    async with AsyncTestClient(app=app) as client:
        yield client


async def test_linking_auto_links_a_battlenet_owned_roster_character(
    battlenet_profile_client: AsyncTestClient,
    discord_state: dict,
    battlenet_state: dict,
    owned_characters: list[dict],
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_sessionmaker() as session:
        session.add(WowCharacter(name="Nox", realm="Whitemane", key="nox-whitemane", blizzard_id=4242, source="import"))
        await session.commit()
    owned_characters.append({"id": 4242, "name": "Nox", "surname": "Zul"})

    await login_as(battlenet_profile_client, discord_state, discord_id=5101)
    response = await link_battlenet(battlenet_profile_client, battlenet_state, account_id=201, battletag="Nox#1111")
    assert response.status_code == 302

    async with db_sessionmaker() as session:
        character = (
            await session.execute(select(WowCharacter).where(WowCharacter.key == "nox-whitemane"))
        ).scalar_one()
    assert character.source == "battlenet"
    assert character.member_id is not None
    me = await battlenet_profile_client.get("/api/me")
    assert character.member_id == me.json()["id"]


async def test_linking_confirms_a_member_who_already_owns_a_roster_character(
    battlenet_profile_client: AsyncTestClient,
    discord_state: dict,
    battlenet_state: dict,
    owned_characters: list[dict],
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_sessionmaker() as session:
        session.add(
            BattlenetCharacter(
                slug="nox-whitemane", blizzard_id=4343, name="Nox", surname="Zul", level=60, in_roster=True
            )
        )
        await session.commit()
    owned_characters.append({"id": 4343, "name": "Nox", "surname": "Zul"})

    await login_as(battlenet_profile_client, discord_state, discord_id=5102)
    response = await link_battlenet(battlenet_profile_client, battlenet_state, account_id=202, battletag="Nox#2222")
    assert response.status_code == 302

    me = await battlenet_profile_client.get("/api/me")
    assert me.json()["roster_confirmed"] is True


async def test_linking_never_overrides_a_claimed_or_officer_linked_character(
    battlenet_profile_client: AsyncTestClient,
    discord_state: dict,
    battlenet_state: dict,
    owned_characters: list[dict],
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_sessionmaker() as session:
        other = Member(discord_id=404, username="claimer", is_guild_member=True)
        session.add(other)
        await session.flush()
        session.add(
            WowCharacter(
                name="Nox", realm="Whitemane", key="nox-whitemane", blizzard_id=4242, member_id=other.id, source="claim"
            )
        )
        await session.commit()
        other_id = other.id
    owned_characters.append({"id": 4242, "name": "Nox", "surname": "Zul"})

    await login_as(battlenet_profile_client, discord_state, discord_id=5102)
    await link_battlenet(battlenet_profile_client, battlenet_state, account_id=202, battletag="Impostor#2222")

    async with db_sessionmaker() as session:
        character = (
            await session.execute(select(WowCharacter).where(WowCharacter.key == "nox-whitemane"))
        ).scalar_one()
    assert (character.member_id, character.source) == (other_id, "claim")


async def test_linking_does_not_link_a_character_without_battlenet_proof(
    battlenet_profile_client: AsyncTestClient,
    discord_state: dict,
    battlenet_state: dict,
    owned_characters: list[dict],
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_sessionmaker() as session:
        session.add(WowCharacter(name="Nox", realm="Whitemane", key="nox-whitemane", blizzard_id=4242, source="import"))
        await session.commit()
    # The account profile reports a different character; 4242 is never proven.
    owned_characters.append({"id": 9999, "name": "Someone", "surname": "Else"})

    await login_as(battlenet_profile_client, discord_state, discord_id=5103)
    await link_battlenet(battlenet_profile_client, battlenet_state, account_id=203, battletag="Stranger#3333")

    async with db_sessionmaker() as session:
        character = (
            await session.execute(select(WowCharacter).where(WowCharacter.key == "nox-whitemane"))
        ).scalar_one()
    assert character.member_id is None


async def test_relinking_battlenet_is_idempotent(
    battlenet_profile_client: AsyncTestClient,
    discord_state: dict,
    battlenet_state: dict,
    owned_characters: list[dict],
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_sessionmaker() as session:
        session.add(WowCharacter(name="Nox", realm="Whitemane", key="nox-whitemane", blizzard_id=4242, source="import"))
        await session.commit()
    owned_characters.append({"id": 4242, "name": "Nox", "surname": "Zul"})

    await login_as(battlenet_profile_client, discord_state, discord_id=5104)
    await link_battlenet(battlenet_profile_client, battlenet_state, account_id=204, battletag="Nox#4444")
    first = await battlenet_profile_client.get("/api/me")

    # Relinking the same account (e.g. the member visits /account/ and links again) must not change anything.
    response = await link_battlenet(battlenet_profile_client, battlenet_state, account_id=204, battletag="Nox#4444")
    assert response.status_code == 302
    second = await battlenet_profile_client.get("/api/me")
    assert first.json() == second.json()

    async with db_sessionmaker() as session:
        characters = (
            (await session.execute(select(WowCharacter).where(WowCharacter.key == "nox-whitemane"))).scalars().all()
        )
    assert len(characters) == 1
    assert characters[0].source == "battlenet"
