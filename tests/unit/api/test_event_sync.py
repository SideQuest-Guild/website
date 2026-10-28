from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select

from sidequest_common.models import DiscordEventTombstone, EventSignup, GuildEvent, Member
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SYNC_PATH = f"/api/guilds/{GUILD_ID}/event-sync"
FOOTER_HEADER = "── SideQuest event ──"


async def _seed_event(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    title: str = "Molten Core",
    kind: str = "raid",
    location: str = "Molten Core",
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    size: int | None = 40,
    status: str = "scheduled",
    notes: str | None = None,
    discord_event_id: int | None = None,
    discord_pushed_hash: str | None = None,
    discord_seen_hash: str | None = None,
) -> GuildEvent:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind=kind,
            title=title,
            location=location,
            starts_at=starts_at or (datetime.now(UTC) + timedelta(days=1)),
            ends_at=ends_at,
            size=size,
            status=status,
            notes=notes,
            discord_event_id=discord_event_id,
            discord_pushed_hash=discord_pushed_hash,
            discord_seen_hash=discord_seen_hash,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event


async def _event_snapshot(db_sessionmaker: async_sessionmaker[AsyncSession], event_id: UUID) -> dict:
    async with db_sessionmaker() as session:
        event = await session.get(GuildEvent, event_id)
        if event is None:
            msg = f"no event {event_id}"
            raise AssertionError(msg)
        return {
            "kind": event.kind,
            "title": event.title,
            "location": event.location,
            "status": event.status,
            "notes": event.notes,
            "starts_at": event.starts_at,
            "ends_at": event.ends_at,
            "size": event.size,
            "discord_event_id": event.discord_event_id,
            "discord_pushed_hash": event.discord_pushed_hash,
            "discord_seen_hash": event.discord_seen_hash,
            "updated_at": event.updated_at,
        }


async def _tombstone_ids(db_sessionmaker: async_sessionmaker[AsyncSession]) -> set[int]:
    async with db_sessionmaker() as session:
        rows = (await session.execute(select(DiscordEventTombstone.discord_event_id))).scalars().all()
        return set(rows)


async def _event_count(db_sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with db_sessionmaker() as session:
        return len((await session.execute(select(GuildEvent))).scalars().all())


async def _push_for(client: AsyncTestClient, event_id: UUID) -> dict:
    pending = (await client.get(f"{SYNC_PATH}/")).json()
    return next(p for p in pending["pushes"] if p["event_id"] == str(event_id))


def _event_from_push(push: dict, event_id: int, *, status: str = "scheduled") -> dict:
    return {
        "id": event_id,
        "name": push["name"],
        "description": push["description"],
        "starts_at": push["starts_at"],
        "ends_at": push["ends_at"],
        "status": status,
        "location": push["location"],
        "channel_id": None,
    }


async def _ack(client: AsyncTestClient, event_id: UUID, event_discord_id: int) -> dict:
    push = await _push_for(client, event_id)
    event = _event_from_push(push, event_discord_id)
    response = await client.post(f"{SYNC_PATH}/{event_id}/ack", json={"push_hash": push["push_hash"], "event": event})
    assert response.status_code == 204
    return event


async def test_pending_lists_future_unlinked_event_not_past(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    future = await _seed_event(db_sessionmaker, title="Future Raid")
    past = await _seed_event(db_sessionmaker, title="Past Raid", starts_at=datetime.now(UTC) - timedelta(days=1))
    response = await client.get(f"{SYNC_PATH}/")
    assert response.status_code == 200
    event_ids = {push["event_id"] for push in response.json()["pushes"]}
    assert str(future.id) in event_ids
    assert str(past.id) not in event_ids


async def test_ack_links_and_clears_pending(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Onyxia's Lair")
    push = await _push_for(client, event.id)
    acked = await _ack(client, event.id, 555_001)
    pending_after = (await client.get(f"{SYNC_PATH}/")).json()
    assert str(event.id) not in {p["event_id"] for p in pending_after["pushes"]}
    snapshot = await _event_snapshot(db_sessionmaker, event.id)
    assert snapshot["discord_event_id"] == acked["id"]
    assert snapshot["discord_pushed_hash"] == push["push_hash"]


async def test_editing_event_makes_it_pending_again(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Zul'Gurub")
    await _ack(client, event.id, 555_002)
    async with db_sessionmaker() as session:
        stored = await session.get(GuildEvent, event.id)
        assert stored is not None
        stored.title = "Zul'Gurub (rescheduled)"
        await session.commit()
    pending = (await client.get(f"{SYNC_PATH}/")).json()
    assert str(event.id) in {p["event_id"] for p in pending["pushes"]}


async def test_new_signup_makes_it_pending_again(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Karazhan")
    await _ack(client, event.id, 555_003)
    async with db_sessionmaker() as session:
        member = Member(discord_id=909090, username="jaina")
        session.add(member)
        await session.flush()
        session.add(
            EventSignup(
                event_id=event.id,
                member_id=member.id,
                character="Jaina",
                wow_class="mage",
                role="dps",
                status="signed",
            )
        )
        await session.commit()
    pending = (await client.get(f"{SYNC_PATH}/")).json()
    assert str(event.id) in {p["event_id"] for p in pending["pushes"]}


async def test_discord_echo_with_acked_state_is_noop(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Blackwing Lair")
    acked = await _ack(client, event.id, 555_004)
    before = await _event_snapshot(db_sessionmaker, event.id)
    response = await client.post(f"{SYNC_PATH}/events", json=acked)
    assert response.status_code == 204
    after = await _event_snapshot(db_sessionmaker, event.id)
    assert after["updated_at"] == before["updated_at"]


async def test_real_discord_edit_updates_fields_and_strips_footer(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Naxxramas")
    acked = await _ack(client, event.id, 555_005)
    new_starts_at = datetime.now(UTC) + timedelta(days=2)
    edited = dict(acked)
    edited["name"] = "Naxxramas (rescheduled)"
    edited["description"] = f"Bring frost resist gear\n\n{FOOTER_HEADER}\nstale footer content"
    edited["starts_at"] = new_starts_at.isoformat()
    response = await client.post(f"{SYNC_PATH}/events", json=edited)
    assert response.status_code == 204
    snapshot = await _event_snapshot(db_sessionmaker, event.id)
    assert snapshot["title"] == "Naxxramas (rescheduled)"
    assert snapshot["notes"] == "Bring frost resist gear"
    assert snapshot["starts_at"] == new_starts_at


async def test_unknown_discord_event_creates_event_with_kind_other_null_size_and_empty_location(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    starts_at = datetime.now(UTC) + timedelta(days=3)
    event = {
        "id": 555_006,
        "name": "Impromptu Dungeon Run",
        "description": "Just vibes",
        "starts_at": starts_at.isoformat(),
        "ends_at": None,
        "status": "scheduled",
        "location": None,
        "channel_id": None,
    }
    response = await client.post(f"{SYNC_PATH}/events", json=event)
    assert response.status_code == 204
    async with db_sessionmaker() as session:
        stored = (await session.execute(select(GuildEvent).where(GuildEvent.discord_event_id == 555_006))).scalar_one()
        assert stored.kind == "other"
        assert stored.size is None
        assert stored.location == ""
        assert stored.title == "Impromptu Dungeon Run"
        assert stored.notes == "Just vibes"
        assert stored.status == "scheduled"


async def test_adoption_via_footer_link_links_instead_of_duplicating(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="The Deadmines")
    push = await _push_for(client, event.id)
    before_count = await _event_count(db_sessionmaker)
    discord_event = _event_from_push(push, 555_007)
    response = await client.post(f"{SYNC_PATH}/events", json=discord_event)
    assert response.status_code == 204
    after_count = await _event_count(db_sessionmaker)
    assert after_count == before_count
    snapshot = await _event_snapshot(db_sessionmaker, event.id)
    assert snapshot["discord_event_id"] == 555_007


async def test_discord_delete_cancels_scheduled_event_and_unlinks(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Stratholme")
    acked = await _ack(client, event.id, 555_008)
    response = await client.delete(f"{SYNC_PATH}/events/{acked['id']}")
    assert response.status_code == 204
    snapshot = await _event_snapshot(db_sessionmaker, event.id)
    assert snapshot["status"] == "cancelled"
    assert snapshot["discord_event_id"] is None
    assert snapshot["discord_pushed_hash"] is None
    assert snapshot["discord_seen_hash"] is None


async def test_reconcile_treats_missing_linked_event_as_deleted_and_drops_stale_tombstones(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    kept_event = await _seed_event(db_sessionmaker, title="Uldaman")
    kept_discord_event = await _ack(client, kept_event.id, 555_009)
    missing_event = await _seed_event(db_sessionmaker, title="Maraudon")
    await _ack(client, missing_event.id, 555_010)
    async with db_sessionmaker() as session:
        session.add(DiscordEventTombstone(discord_event_id=555_011))
        await session.commit()

    response = await client.post(f"{SYNC_PATH}/reconcile", json={"events": [kept_discord_event]})
    assert response.status_code == 204

    missing_snapshot = await _event_snapshot(db_sessionmaker, missing_event.id)
    assert missing_snapshot["status"] == "cancelled"
    assert missing_snapshot["discord_event_id"] is None

    kept_snapshot = await _event_snapshot(db_sessionmaker, kept_event.id)
    assert kept_snapshot["discord_event_id"] == 555_009

    assert await _tombstone_ids(db_sessionmaker) == set()


async def test_site_delete_of_linked_event_produces_tombstone(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Scholomance", discord_event_id=555_012)
    async with db_sessionmaker() as session:
        await session.execute(delete(GuildEvent).where(GuildEvent.id == event.id))
        session.add(DiscordEventTombstone(discord_event_id=555_012))
        await session.commit()
    pending = (await client.get(f"{SYNC_PATH}/")).json()
    assert 555_012 in pending["deletions"]


async def test_ack_for_deleted_event_tombstones_the_event(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Razorfen Kraul")
    push = await _push_for(client, event.id)
    discord_event = _event_from_push(push, 555_013)
    async with db_sessionmaker() as session:
        await session.execute(delete(GuildEvent).where(GuildEvent.id == event.id))
        await session.commit()
    response = await client.post(
        f"{SYNC_PATH}/{event.id}/ack", json={"push_hash": push["push_hash"], "event": discord_event}
    )
    assert response.status_code == 204
    assert 555_013 in await _tombstone_ids(db_sessionmaker)


async def test_wrong_guild_id_is_404(client: AsyncTestClient) -> None:
    response = await client.get(f"/api/guilds/{GUILD_ID + 1}/event-sync/")
    assert response.status_code == 404


async def test_description_stays_within_limit_with_long_notes(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Molten Core", notes="x" * 2000)
    push = await _push_for(client, event.id)
    assert len(push["description"]) <= 1000
    assert push["description"].endswith(f"Details & sign-up: http://localhost:8000/events/detail/?id={event.id}")
    assert FOOTER_HEADER in push["description"]


async def test_footer_has_kind_label_and_signed_line_for_raid(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Molten Core", kind="raid")
    push = await _push_for(client, event.id)
    assert "Raid · Molten Core · 40-player" in push["description"]
    assert "Signed: 0 tanks · 0 healers · 0 dps" in push["description"]


async def test_footer_has_going_line_for_social_event(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Guild Game Night", kind="social", location="", size=None)
    push = await _push_for(client, event.id)
    assert "Social" in push["description"]
    assert "Going: 0" in push["description"]
    assert "Signed:" not in push["description"]
