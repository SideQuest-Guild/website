from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sidequest_common.models import Raid
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _seed_raid(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    title: str = "Molten Core",
    starts_at: datetime | None = None,
    status: str = "scheduled",
    size: int = 40,
) -> str:
    async with db_sessionmaker() as session:
        raid = Raid(
            title=title,
            instance="Molten Core",
            starts_at=starts_at or (datetime.now(UTC) + timedelta(days=1)),
            size=size,
            status=status,
            notes=None,
        )
        session.add(raid)
        await session.commit()
        await session.refresh(raid)
        return str(raid.id)


def _signup_body(character: str = "Thrall", role: str = "dps", status: str = "signed") -> dict:
    return {"character": character, "class": "warrior", "role": role, "status": status, "comment": None}


async def test_non_member_gets_403_on_signup(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid_id = await _seed_raid(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=2001, is_guild_member=False)
    response = await member_client.put(f"/api/raids/{raid_id}/signup", json=_signup_body())
    assert response.status_code == 403


async def test_officer_only_endpoint_is_403_for_regular_member(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=2002, roles=[])
    response = await member_client.post(
        "/api/raids",
        json={
            "title": "Onyxia's Lair",
            "instance": "Onyxia",
            "starts_at": "2026-12-01T20:00:00Z",
            "size": 40,
            "notes": None,
        },
    )
    assert response.status_code == 403


async def test_signup_upsert_keeps_one_row(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid_id = await _seed_raid(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=2003, roles=[])

    first = await member_client.put(f"/api/raids/{raid_id}/signup", json=_signup_body(character="Thrall"))
    assert first.status_code == 200
    second = await member_client.put(
        f"/api/raids/{raid_id}/signup", json=_signup_body(character="Jaina", role="healer")
    )
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["class"] == "warrior"  # wire name per the contract, not the Python attribute

    detail = await member_client.get(f"/api/raids/{raid_id}")
    assert len(detail.json()["signups"]) == 1
    assert detail.json()["signups"][0]["character"] == "Jaina"
    assert detail.json()["signups"][0]["role"] == "healer"


async def test_counts_only_count_signed_signups(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid_id = await _seed_raid(db_sessionmaker)

    await login_as(member_client, discord_state, discord_id=2010, roles=[])
    await member_client.put(
        f"/api/raids/{raid_id}/signup", json=_signup_body(character="Tank1", role="tank", status="signed")
    )

    await login_as(member_client, discord_state, discord_id=2011, roles=[])
    await member_client.put(
        f"/api/raids/{raid_id}/signup", json=_signup_body(character="Heal1", role="healer", status="tentative")
    )

    await login_as(member_client, discord_state, discord_id=2012, roles=[])
    await member_client.put(
        f"/api/raids/{raid_id}/signup", json=_signup_body(character="Dps1", role="dps", status="absent")
    )

    response = await member_client.get(f"/api/raids/{raid_id}")
    counts = response.json()["counts"]
    assert counts == {"tank": 1, "healer": 0, "dps": 0, "tentative": 1, "absent": 1}


async def test_upcoming_and_past_split(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    now = datetime.now(UTC)
    future_id = await _seed_raid(db_sessionmaker, title="Future Raid", starts_at=now + timedelta(days=3))
    past_id = await _seed_raid(db_sessionmaker, title="Past Raid", starts_at=now - timedelta(days=3))
    # Marked done the same evening: still inside the upcoming look-back window, but it belongs in past.
    done_id = await _seed_raid(
        db_sessionmaker, title="Done Tonight", starts_at=now - timedelta(hours=1), status="completed"
    )

    upcoming = await member_client.get("/api/raids", params={"when": "upcoming"})
    past = await member_client.get("/api/raids", params={"when": "past"})

    upcoming_ids = [raid["id"] for raid in upcoming.json()]
    past_ids = [raid["id"] for raid in past.json()]
    assert future_id in upcoming_ids
    assert future_id not in past_ids
    assert past_id in past_ids
    assert past_id not in upcoming_ids
    assert done_id in past_ids
    assert done_id not in upcoming_ids


async def test_signup_to_cancelled_raid_is_409(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid_id = await _seed_raid(db_sessionmaker, status="cancelled")
    await login_as(member_client, discord_state, discord_id=2020, roles=[])
    response = await member_client.put(f"/api/raids/{raid_id}/signup", json=_signup_body())
    assert response.status_code == 409


async def test_officer_can_create_and_manage_raid(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=2030, roles=[OFFICER_ROLE_ID])
    create_response = await member_client.post(
        "/api/raids",
        json={
            "title": "Blackwing Lair",
            "instance": "Blackwing Lair",
            "starts_at": "2026-12-05T20:00:00Z",
            "size": 40,
            "notes": "Bring flasks",
        },
    )
    assert create_response.status_code == 201
    raid_id = create_response.json()["id"]

    update_response = await member_client.patch(f"/api/raids/{raid_id}", json={"status": "cancelled"})
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "cancelled"

    delete_response = await member_client.delete(f"/api/raids/{raid_id}")
    assert delete_response.status_code == 204


async def test_officer_raid_chart_places_signup_in_group(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid_id = await _seed_raid(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=2040, roles=[])
    signup = await member_client.put(f"/api/raids/{raid_id}/signup", json=_signup_body())
    signup_id = signup.json()["id"]

    await login_as(member_client, discord_state, discord_id=2041, roles=[OFFICER_ROLE_ID])
    chart_response = await member_client.patch(
        f"/api/raids/{raid_id}/signups/{signup_id}", json={"group": 3, "bench": False}
    )
    assert chart_response.status_code == 200
    assert chart_response.json()["group"] == 3
    assert chart_response.json()["bench"] is False
