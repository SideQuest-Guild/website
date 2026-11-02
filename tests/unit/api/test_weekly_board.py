from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sidequest_common.models import EventSignup, GuildEvent, Member
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from uuid import UUID

    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

WEEKLY_BOARD_PATH = f"/api/guilds/{GUILD_ID}/weekly-board/events"
SYNC_PATH = f"/api/guilds/{GUILD_ID}/event-sync"
START = "2026-11-02T00:00:00Z"
END = "2026-11-09T00:00:00Z"


async def _seed_raid(db_sessionmaker: async_sessionmaker[AsyncSession], *, starts_at: datetime) -> UUID:
    async with db_sessionmaker() as session:
        event = GuildEvent(kind="raid", title="Molten Core", location="Blackrock", starts_at=starts_at)
        session.add(event)
        await session.commit()
        return event.id


async def _sign_up(
    db_sessionmaker: async_sessionmaker[AsyncSession], event_id: UUID, discord_id: int, status: str
) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=discord_id, username=f"member{discord_id}")
        session.add(member)
        await session.flush()
        role_fields = {"character": "Thrall", "wow_class": "shaman", "role": "healer"} if status != "absent" else {}
        session.add(EventSignup(event_id=event_id, member_id=member.id, status=status, **role_fields))
        await session.commit()


async def _pending_push(client: AsyncTestClient, event_id: UUID) -> dict | None:
    pending = (await client.get(f"{SYNC_PATH}/")).json()
    return next((push for push in pending["pushes"] if push["event_id"] == str(event_id)), None)


async def _ack(client: AsyncTestClient, push: dict) -> None:
    event = {
        "id": 555_100,
        "name": push["name"],
        "description": push["description"],
        "starts_at": push["starts_at"],
        "ends_at": push["ends_at"],
        "status": "scheduled",
        "location": push["location"],
        "channel_id": None,
    }
    response = await client.post(
        f"{SYNC_PATH}/{push['event_id']}/ack", json={"push_hash": push["push_hash"], "event": event}
    )
    assert response.status_code == 204


async def test_wrong_guild_id_is_404(client: AsyncTestClient) -> None:
    response = await client.get(f"/api/guilds/{GUILD_ID + 1}/weekly-board/events", params={"start": START, "end": END})
    assert response.status_code == 404


async def test_requires_api_key(client: AsyncTestClient) -> None:
    client.headers.pop("X-API-Key")
    response = await client.get(WEEKLY_BOARD_PATH, params={"start": START, "end": END})
    assert response.status_code == 401


async def test_empty_week_returns_empty_list(client: AsyncTestClient) -> None:
    response = await client.get(WEEKLY_BOARD_PATH, params={"start": START, "end": END})
    assert response.status_code == 200
    assert response.json() == []


async def test_returns_only_events_within_the_range_in_order_with_thread_id(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        session.add_all(
            [
                GuildEvent(
                    kind="raid",
                    title="Molten Core",
                    location="",
                    starts_at=datetime(2026, 11, 5, 19, 0, tzinfo=UTC),
                    status="scheduled",
                    discord_thread_id=555,
                ),
                GuildEvent(
                    kind="dungeon",
                    title="Heroics",
                    location="",
                    starts_at=datetime(2026, 11, 3, 19, 0, tzinfo=UTC),
                    status="scheduled",
                ),
                GuildEvent(
                    kind="social",
                    title="Out of range",
                    location="",
                    starts_at=datetime(2026, 11, 9, 19, 0, tzinfo=UTC),
                    status="scheduled",
                ),
                GuildEvent(
                    kind="raid",
                    title="Cancelled Raid",
                    location="",
                    starts_at=datetime(2026, 11, 4, 19, 0, tzinfo=UTC),
                    status="cancelled",
                ),
            ]
        )
        await session.commit()

    response = await client.get(WEEKLY_BOARD_PATH, params={"start": START, "end": END})
    assert response.status_code == 200
    titles = [event["title"] for event in response.json()]
    assert titles == ["Heroics", "Molten Core"]
    assert response.json()[1]["discord_thread_id"] == 555
    assert response.json()[0]["discord_thread_id"] is None


async def test_lists_signups_in_signup_order_with_class_and_role(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_raid(db_sessionmaker, starts_at=datetime(2026, 11, 5, 19, 0, tzinfo=UTC))
    await _sign_up(db_sessionmaker, event_id, 222, "signed")
    await _sign_up(db_sessionmaker, event_id, 111, "absent")

    response = await client.get(WEEKLY_BOARD_PATH, params={"start": START, "end": END})

    (event,) = response.json()
    assert event["location"] == "Blackrock"
    assert event["signups"] == [
        {"status": "signed", "discord_id": 222, "class": "shaman", "role": "healer"},
        {"status": "absent", "discord_id": 111, "class": None, "role": None},
    ]


async def test_recording_a_card_for_an_unknown_event_is_404(client: AsyncTestClient) -> None:
    response = await client.put(
        f"{WEEKLY_BOARD_PATH}/00000000-0000-0000-0000-000000000000/message",
        json={"channel_id": 1, "message_id": 2},
    )
    assert response.status_code == 404


async def test_a_card_rides_the_event_sync_and_any_signup_change_repushes_it(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_raid(db_sessionmaker, starts_at=datetime.now(UTC) + timedelta(days=1))
    push = await _pending_push(client, event_id)
    assert push is not None
    assert push["board_message_id"] is None
    assert push["board_signups"] == []
    await _ack(client, push)

    response = await client.put(f"{WEEKLY_BOARD_PATH}/{event_id}/message", json={"channel_id": 77, "message_id": 88})
    assert response.status_code == 204
    push = await _pending_push(client, event_id)
    assert push is not None
    assert (push["board_channel_id"], push["board_message_id"]) == (77, 88)
    await _ack(client, push)
    assert await _pending_push(client, event_id) is None

    # A "can't make it" leaves the raid footer's counts alone, so only the card's lists change.
    await _sign_up(db_sessionmaker, event_id, 333, "absent")
    push = await _pending_push(client, event_id)
    assert push is not None
    assert push["board_signups"] == [{"status": "absent", "discord_id": 333, "class": None, "role": None}]


async def test_an_event_without_a_card_is_not_repushed_for_a_signup_its_footer_ignores(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_raid(db_sessionmaker, starts_at=datetime.now(UTC) + timedelta(days=1))
    push = await _pending_push(client, event_id)
    assert push is not None
    await _ack(client, push)

    await _sign_up(db_sessionmaker, event_id, 444, "absent")

    assert await _pending_push(client, event_id) is None
