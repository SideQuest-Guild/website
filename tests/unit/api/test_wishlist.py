"""Wishlists: a member's own list at ``/api/me/wishlist``, and who wants an item for officers."""

from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import select

from sidequest_api.app import create_app
from sidequest_common.models import ItemWish, Member
from sidequest_common.schemas import MAX_ITEM_WISHES
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import TEST_API_KEY
from tests.unit.api.conftest import OFFICER_ROLE_ID, _discord_transport, login_as
from tests.unit.api.fake_battlenet import THUNDERFURY, battlenet, forget_battlenet_state, transport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ("battlenet", "forget_battlenet_state")  # fixtures, used by name

WISHLIST = "/api/me/wishlist"


@pytest.fixture
async def wish_client(
    database_url: str, member_web_settings: WebSettings, discord_state: dict, battlenet: dict
) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Member sign-in plus the fake Battle.net, cookies kept across requests like a browser."""
    battlenet["items"][2589] = "Linen Cloth"
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        member_web_settings,
        discord_transport=_discord_transport(discord_state),
        game_data_transport=transport(battlenet),
    )
    async with AsyncTestClient(app=app) as client:
        yield client


async def test_a_member_adds_notes_and_removes_wishes(wish_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(wish_client, discord_state, discord_id=7001)

    first = await wish_client.put(f"{WISHLIST}/19019", json={"note": "  for my warrior  "})
    again = await wish_client.put(f"{WISHLIST}/19019", json={"note": "off spec"})
    await wish_client.put(f"{WISHLIST}/2589", json={})

    assert first.status_code == 200
    assert [(wish["item_id"], wish["note"]) for wish in first.json()] == [(19019, "for my warrior")]
    assert [(wish["item_id"], wish["note"]) for wish in again.json()] == [(19019, "off spec")]
    listed = (await wish_client.get(WISHLIST)).json()
    assert [wish["item_id"] for wish in listed] == [2589, 19019]
    assert listed[1]["name"] == THUNDERFURY
    assert listed[1]["quality"] == "EPIC"

    removed = await wish_client.delete(f"{WISHLIST}/19019")
    removed_again = await wish_client.delete(f"{WISHLIST}/19019")

    assert (removed.status_code, removed_again.status_code) == (204, 204)
    assert [wish["item_id"] for wish in (await wish_client.get(WISHLIST)).json()] == [2589]


async def test_only_items_battlenet_knows_can_be_wished_for(wish_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(wish_client, discord_state, discord_id=7002)

    response = await wish_client.put(f"{WISHLIST}/424242", json={})

    assert response.status_code == 404
    assert (await wish_client.get(WISHLIST)).json() == []


async def test_a_full_wishlist_refuses_another_item(
    wish_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(wish_client, discord_state, discord_id=7003)
    async with db_sessionmaker() as session:
        member = (await session.execute(select(Member).where(Member.discord_id == 7003))).scalar_one()
        session.add_all(ItemWish(member_id=member.id, item_id=900_000 + n) for n in range(MAX_ITEM_WISHES))
        await session.commit()

    full = await wish_client.put(f"{WISHLIST}/19019", json={})
    note_on_existing = await wish_client.put(f"{WISHLIST}/900000", json={"note": "still fine"})

    assert full.status_code == 409
    assert note_on_existing.status_code != 409


async def test_the_wishlist_needs_a_signed_in_guild_member(wish_client: AsyncTestClient, discord_state: dict) -> None:
    assert (await wish_client.get(WISHLIST)).status_code == 401
    await login_as(wish_client, discord_state, discord_id=7004, is_guild_member=False)
    assert (await wish_client.put(f"{WISHLIST}/19019", json={})).status_code == 403


async def test_officers_see_who_wants_an_item(wish_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(wish_client, discord_state, discord_id=7005, username="wanter")
    await wish_client.put(f"{WISHLIST}/19019", json={"note": "BiS"})
    assert (await wish_client.get("/api/items/19019/wishers")).status_code == 403

    await login_as(wish_client, discord_state, discord_id=7006, username="officer", roles=[OFFICER_ROLE_ID])
    response = await wish_client.get("/api/items/19019/wishers")

    assert response.status_code == 200
    wishers = response.json()
    assert [(wisher["member_name"], wisher["note"]) for wisher in wishers] == [("wanter", "BiS")]
    assert set(wishers[0]) >= {"ep", "gp", "pr", "trial", "added_at"}
    assert (await wish_client.get("/api/items/2589/wishers")).json() == []


async def test_deleting_an_account_deletes_its_wishes(
    wish_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(wish_client, discord_state, discord_id=7007)
    await wish_client.put(f"{WISHLIST}/19019", json={})

    response = await wish_client.delete("/api/me")

    assert response.status_code == 204
    async with db_sessionmaker() as session:
        assert (await session.execute(select(ItemWish))).scalars().all() == []
