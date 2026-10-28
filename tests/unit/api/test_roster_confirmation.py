from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import Member
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _signed_in_member_id(client: AsyncTestClient, discord_state: dict, *, discord_id: int) -> int:
    await login_as(client, discord_state, discord_id=discord_id, username=f"member-{discord_id}", roles=[])
    return (await client.get("/api/me")).json()["id"]


async def test_confirm_requires_signed_in(member_client: AsyncTestClient) -> None:
    response = await member_client.put("/api/members/1/roster-confirmation")
    assert response.status_code == 401


async def test_confirm_requires_officer(member_client: AsyncTestClient, discord_state: dict) -> None:
    member_id = await _signed_in_member_id(member_client, discord_state, discord_id=7002)
    await login_as(member_client, discord_state, discord_id=7003, username="rando", roles=[])
    response = await member_client.put(f"/api/members/{member_id}/roster-confirmation")
    assert response.status_code == 403


async def test_confirm_unknown_member_is_404(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=7004, username="officer", roles=[OFFICER_ROLE_ID])
    response = await member_client.put("/api/members/999999/roster-confirmation")
    assert response.status_code == 404


async def test_officer_confirms_member_roster(member_client: AsyncTestClient, discord_state: dict) -> None:
    member_id = await _signed_in_member_id(member_client, discord_state, discord_id=7005)

    await login_as(member_client, discord_state, discord_id=7006, username="officer", roles=[OFFICER_ROLE_ID])
    response = await member_client.put(f"/api/members/{member_id}/roster-confirmation")
    assert response.status_code == 200
    assert response.json()["roster_confirmed"] is True

    listing = await member_client.get("/api/members")
    by_id = {row["id"]: row for row in listing.json()}
    assert by_id[member_id]["roster_confirmed"] is True

    await login_as(member_client, discord_state, discord_id=7005, username="member-7005", roles=[])
    assert (await member_client.get("/api/me")).json()["roster_confirmed"] is True


async def test_confirm_is_idempotent_keeps_first_timestamp(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id = await _signed_in_member_id(member_client, discord_state, discord_id=7007)
    await login_as(member_client, discord_state, discord_id=7008, username="officer", roles=[OFFICER_ROLE_ID])

    first = await member_client.put(f"/api/members/{member_id}/roster-confirmation")
    assert first.status_code == 200
    async with db_sessionmaker() as session:
        first_confirmed_at = (
            (await session.scalars(select(Member).where(Member.id == member_id))).one().roster_confirmed_at
        )

    second = await member_client.put(f"/api/members/{member_id}/roster-confirmation")
    assert second.status_code == 200
    async with db_sessionmaker() as session:
        second_confirmed_at = (
            (await session.scalars(select(Member).where(Member.id == member_id))).one().roster_confirmed_at
        )

    assert first_confirmed_at == second_confirmed_at


async def test_unconfirm_requires_signed_in(member_client: AsyncTestClient) -> None:
    response = await member_client.delete("/api/members/1/roster-confirmation")
    assert response.status_code == 401


async def test_unconfirm_requires_officer(member_client: AsyncTestClient, discord_state: dict) -> None:
    member_id = await _signed_in_member_id(member_client, discord_state, discord_id=7010)
    await login_as(member_client, discord_state, discord_id=7011, username="rando", roles=[])
    response = await member_client.delete(f"/api/members/{member_id}/roster-confirmation")
    assert response.status_code == 403


async def test_unconfirm_unknown_member_is_404(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=7012, username="officer", roles=[OFFICER_ROLE_ID])
    response = await member_client.delete("/api/members/999999/roster-confirmation")
    assert response.status_code == 404


async def test_officer_unconfirms_member_roster(member_client: AsyncTestClient, discord_state: dict) -> None:
    member_id = await _signed_in_member_id(member_client, discord_state, discord_id=7013)
    await login_as(member_client, discord_state, discord_id=7014, username="officer", roles=[OFFICER_ROLE_ID])
    await member_client.put(f"/api/members/{member_id}/roster-confirmation")

    response = await member_client.delete(f"/api/members/{member_id}/roster-confirmation")
    assert response.status_code == 200
    assert response.json()["roster_confirmed"] is False

    listing = await member_client.get("/api/members")
    by_id = {row["id"]: row for row in listing.json()}
    assert by_id[member_id]["roster_confirmed"] is False
