"""``/api/me/away`` (member CRUD) and ``/api/guilds/{guild_id}/away-now`` (bot-key)."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sidequest_common.models import Member, MemberAwayRange
from tests.conftest import GUILD_ID
from tests.unit.api.conftest import login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _iso(days_from_today: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days_from_today)).date().isoformat()


async def test_away_requires_sign_in(member_client: AsyncTestClient) -> None:
    assert (await member_client.get("/api/me/away")).status_code == 401
    assert (
        await member_client.post("/api/me/away", json={"start_date": _iso(1), "end_date": _iso(2)})
    ).status_code == 401


async def test_add_and_list_away_ranges_soonest_first(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6001)
    later = await member_client.post(
        "/api/me/away", json={"start_date": _iso(10), "end_date": _iso(12), "note": "Vacation"}
    )
    assert later.status_code == 201
    sooner = await member_client.post("/api/me/away", json={"start_date": _iso(1), "end_date": _iso(3), "note": None})
    assert sooner.status_code == 201
    assert sooner.json()["note"] is None

    listing = await member_client.get("/api/me/away")
    assert listing.status_code == 200
    rows = listing.json()
    assert [row["id"] for row in rows] == [sooner.json()["id"], later.json()["id"]]
    assert rows[1]["note"] == "Vacation"


async def test_end_date_before_start_date_is_rejected(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6002)
    response = await member_client.post("/api/me/away", json={"start_date": _iso(5), "end_date": _iso(1)})
    assert response.status_code == 400


async def test_note_over_100_chars_is_rejected(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6003)
    response = await member_client.post(
        "/api/me/away", json={"start_date": _iso(1), "end_date": _iso(2), "note": "x" * 101}
    )
    assert response.status_code == 400


async def test_delete_removes_only_the_members_own_range(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6004)
    created = await member_client.post("/api/me/away", json={"start_date": _iso(1), "end_date": _iso(2)})
    range_id = created.json()["id"]

    deleted = await member_client.delete(f"/api/me/away/{range_id}")
    assert deleted.status_code == 204
    assert (await member_client.get("/api/me/away")).json() == []


async def test_delete_unknown_range_404s(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6005)
    response = await member_client.delete("/api/me/away/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_delete_someone_elses_range_404s(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=6006)
    async with db_sessionmaker() as session:
        other = Member(discord_id=999999, username="other")
        session.add(other)
        await session.flush()
        other_range = MemberAwayRange(
            member_id=other.id,
            start_date=(datetime.now(UTC) + timedelta(days=1)).date(),
            end_date=(datetime.now(UTC) + timedelta(days=2)).date(),
        )
        session.add(other_range)
        await session.commit()
        await session.refresh(other_range)
        other_range_id = str(other_range.id)

    response = await member_client.delete(f"/api/me/away/{other_range_id}")
    assert response.status_code == 404


async def test_listing_prunes_ranges_that_already_ended(
    member_client: AsyncTestClient,
    discord_state: dict,
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await login_as(member_client, discord_state, discord_id=6007)
    me = (await member_client.get("/api/me")).json()
    async with db_sessionmaker() as session:
        past = MemberAwayRange(
            member_id=me["id"],
            start_date=(datetime.now(UTC) - timedelta(days=10)).date(),
            end_date=(datetime.now(UTC) - timedelta(days=5)).date(),
        )
        session.add(past)
        await session.commit()

    assert (await member_client.get("/api/me/away")).json() == []
    async with db_sessionmaker() as session:
        remaining = await session.get(MemberAwayRange, past.id)
        assert remaining is None


async def test_away_now_wrong_guild_404s(client: AsyncTestClient) -> None:
    response = await client.get("/api/guilds/1/away-now")
    assert response.status_code == 404


async def test_away_now_requires_api_key(member_client: AsyncTestClient) -> None:
    response = await member_client.get(f"/api/guilds/{GUILD_ID}/away-now")
    assert response.status_code == 401


async def test_away_now_lists_only_members_away_today(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        away_today = Member(discord_id=7001, username="away-now")
        not_away = Member(discord_id=7002, username="not-away")
        future_away = Member(discord_id=7003, username="away-later")
        session.add_all([away_today, not_away, future_away])
        await session.flush()
        today = datetime.now(UTC).date()
        session.add_all(
            [
                MemberAwayRange(
                    member_id=away_today.id, start_date=today - timedelta(days=1), end_date=today + timedelta(days=1)
                ),
                MemberAwayRange(
                    member_id=future_away.id, start_date=today + timedelta(days=5), end_date=today + timedelta(days=7)
                ),
            ]
        )
        await session.commit()

    response = await client.get(f"/api/guilds/{GUILD_ID}/away-now")
    assert response.status_code == 200
    assert response.json()["discord_ids"] == [7001]
