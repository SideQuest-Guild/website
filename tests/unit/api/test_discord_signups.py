"""Tests for the bot-key event sign-up lookup/upsert by Discord id (Discord's Going/Maybe/Can't buttons)."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import EventSignup, EventSignupActivity, GuildEvent, Member
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _seed_event(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    kind: str = "raid",
    status: str = "scheduled",
) -> str:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind=kind,
            title="Molten Core",
            location="Molten Core",
            starts_at=datetime.now(UTC) + timedelta(days=1),
            size=40,
            status=status,
            notes=None,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return str(event.id)


async def _seed_member(db_sessionmaker: async_sessionmaker[AsyncSession], *, discord_id: int, username: str) -> int:
    async with db_sessionmaker() as session:
        member = Member(discord_id=discord_id, username=username, roles=[])
        session.add(member)
        await session.commit()
        await session.refresh(member)
        return member.id


def _path(event_id: str, discord_id: int) -> str:
    return f"/api/guilds/{GUILD_ID}/events/{event_id}/signups/by-discord/{discord_id}"


async def test_wrong_guild_404(client: AsyncTestClient) -> None:
    response = await client.get("/api/guilds/999999/events/00000000-0000-0000-0000-000000000000/signups/by-discord/1")
    assert response.status_code == 404


async def test_get_no_site_account_404(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    response = await client.get(_path(event_id, 123456))
    assert response.status_code == 404


async def test_put_no_site_account_404(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    response = await client.put(_path(event_id, 123456), json={"status": "absent"})
    assert response.status_code == 404


async def test_put_event_not_scheduled_409(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, status="cancelled")
    await _seed_member(db_sessionmaker, discord_id=4001, username="coffee")
    response = await client.put(_path(event_id, 4001), json={"status": "absent"})
    assert response.status_code == 409


async def test_get_event_not_found_404(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_member(db_sessionmaker, discord_id=4002, username="coffee")
    response = await client.get(_path("00000000-0000-0000-0000-000000000000", 4002))
    assert response.status_code == 404


async def test_get_with_no_signup_yet_returns_nulls(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await _seed_member(db_sessionmaker, discord_id=4003, username="coffee")
    response = await client.get(_path(event_id, 4003))
    assert response.status_code == 200
    body = response.json()
    assert body["signup"] is None
    assert body["defaults"] is None
    assert body["kind"] == "raid"


async def test_get_returns_current_signup_and_defaults_from_another_event(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    other_event_id = await _seed_event(db_sessionmaker)
    event_id = await _seed_event(db_sessionmaker)
    member_id = await _seed_member(db_sessionmaker, discord_id=4004, username="coffee")
    async with db_sessionmaker() as session:
        session.add(
            EventSignup(
                event_id=other_event_id,
                member_id=member_id,
                character="Oakenshield",
                wow_class="warrior",
                role="tank",
                status="signed",
            )
        )
        session.add(EventSignup(event_id=event_id, member_id=member_id, status="tentative"))
        await session.commit()
    response = await client.get(_path(event_id, 4004))
    assert response.status_code == 200
    body = response.json()
    assert body["signup"]["status"] == "tentative"
    assert body["defaults"] == {"character": "Oakenshield", "class": "warrior", "role": "tank"}


async def test_put_absent_without_character_succeeds_and_writes_activity_row(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="raid")
    await _seed_member(db_sessionmaker, discord_id=4005, username="coffee")
    response = await client.put(_path(event_id, 4005), json={"status": "absent"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "absent"
    assert body["character"] is None
    async with db_sessionmaker() as session:
        rows = (await session.execute(select(EventSignupActivity))).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "not_going"
    assert rows[0].discord_id == 4005


async def test_put_role_kind_without_character_is_400(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="raid")
    await _seed_member(db_sessionmaker, discord_id=4006, username="coffee")
    response = await client.put(_path(event_id, 4006), json={"status": "signed"})
    assert response.status_code == 400


async def test_put_with_character_succeeds(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="raid")
    await _seed_member(db_sessionmaker, discord_id=4007, username="coffee")
    response = await client.put(
        _path(event_id, 4007),
        json={"status": "signed", "character": "Oakenshield", "class": "warrior", "role": "tank"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["character"] == "Oakenshield"
    assert body["class"] == "warrior"
    assert body["role"] == "tank"
