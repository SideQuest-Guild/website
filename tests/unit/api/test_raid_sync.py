from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select

from sidequest_common.models import DiscordEventTombstone, Member, Raid, RaidSignup
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SYNC_PATH = f"/api/guilds/{GUILD_ID}/raid-sync"
FOOTER_HEADER = "── SideQuest raid ──"


async def _seed_raid(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    title: str = "Molten Core",
    instance: str = "Molten Core",
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    size: int | None = 40,
    status: str = "scheduled",
    notes: str | None = None,
    discord_event_id: int | None = None,
    discord_pushed_hash: str | None = None,
    discord_seen_hash: str | None = None,
) -> Raid:
    async with db_sessionmaker() as session:
        raid = Raid(
            title=title,
            instance=instance,
            starts_at=starts_at or (datetime.now(UTC) + timedelta(days=1)),
            ends_at=ends_at,
            size=size,
            status=status,
            notes=notes,
            discord_event_id=discord_event_id,
            discord_pushed_hash=discord_pushed_hash,
            discord_seen_hash=discord_seen_hash,
        )
        session.add(raid)
        await session.commit()
        await session.refresh(raid)
        return raid


async def _raid_snapshot(db_sessionmaker: async_sessionmaker[AsyncSession], raid_id: UUID) -> dict:
    async with db_sessionmaker() as session:
        raid = await session.get(Raid, raid_id)
        if raid is None:
            msg = f"no raid {raid_id}"
            raise AssertionError(msg)
        return {
            "title": raid.title,
            "instance": raid.instance,
            "status": raid.status,
            "notes": raid.notes,
            "starts_at": raid.starts_at,
            "ends_at": raid.ends_at,
            "size": raid.size,
            "discord_event_id": raid.discord_event_id,
            "discord_pushed_hash": raid.discord_pushed_hash,
            "discord_seen_hash": raid.discord_seen_hash,
            "updated_at": raid.updated_at,
        }


async def _tombstone_ids(db_sessionmaker: async_sessionmaker[AsyncSession]) -> set[int]:
    async with db_sessionmaker() as session:
        rows = (await session.execute(select(DiscordEventTombstone.discord_event_id))).scalars().all()
        return set(rows)


async def _raid_count(db_sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with db_sessionmaker() as session:
        return len((await session.execute(select(Raid))).scalars().all())


async def _push_for(client: AsyncTestClient, raid_id: UUID) -> dict:
    pending = (await client.get(f"{SYNC_PATH}/")).json()
    return next(p for p in pending["pushes"] if p["raid_id"] == str(raid_id))


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


async def _ack(client: AsyncTestClient, raid_id: UUID, event_id: int) -> dict:
    push = await _push_for(client, raid_id)
    event = _event_from_push(push, event_id)
    response = await client.post(f"{SYNC_PATH}/{raid_id}/ack", json={"push_hash": push["push_hash"], "event": event})
    assert response.status_code == 204
    return event


async def test_pending_lists_future_unlinked_raid_not_past(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    future = await _seed_raid(db_sessionmaker, title="Future Raid")
    past = await _seed_raid(db_sessionmaker, title="Past Raid", starts_at=datetime.now(UTC) - timedelta(days=1))
    response = await client.get(f"{SYNC_PATH}/")
    assert response.status_code == 200
    raid_ids = {push["raid_id"] for push in response.json()["pushes"]}
    assert str(future.id) in raid_ids
    assert str(past.id) not in raid_ids


async def test_ack_links_and_clears_pending(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid = await _seed_raid(db_sessionmaker, title="Onyxia's Lair")
    push = await _push_for(client, raid.id)
    event = await _ack(client, raid.id, 555_001)
    pending_after = (await client.get(f"{SYNC_PATH}/")).json()
    assert str(raid.id) not in {p["raid_id"] for p in pending_after["pushes"]}
    snapshot = await _raid_snapshot(db_sessionmaker, raid.id)
    assert snapshot["discord_event_id"] == event["id"]
    assert snapshot["discord_pushed_hash"] == push["push_hash"]


async def test_editing_raid_makes_it_pending_again(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid = await _seed_raid(db_sessionmaker, title="Zul'Gurub")
    await _ack(client, raid.id, 555_002)
    async with db_sessionmaker() as session:
        stored = await session.get(Raid, raid.id)
        assert stored is not None
        stored.title = "Zul'Gurub (rescheduled)"
        await session.commit()
    pending = (await client.get(f"{SYNC_PATH}/")).json()
    assert str(raid.id) in {p["raid_id"] for p in pending["pushes"]}


async def test_new_signup_makes_it_pending_again(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid = await _seed_raid(db_sessionmaker, title="Karazhan")
    await _ack(client, raid.id, 555_003)
    async with db_sessionmaker() as session:
        member = Member(discord_id=909090, username="jaina")
        session.add(member)
        await session.flush()
        session.add(
            RaidSignup(
                raid_id=raid.id, member_id=member.id, character="Jaina", wow_class="mage", role="dps", status="signed"
            )
        )
        await session.commit()
    pending = (await client.get(f"{SYNC_PATH}/")).json()
    assert str(raid.id) in {p["raid_id"] for p in pending["pushes"]}


async def test_discord_echo_with_acked_state_is_noop(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid = await _seed_raid(db_sessionmaker, title="Blackwing Lair")
    event = await _ack(client, raid.id, 555_004)
    before = await _raid_snapshot(db_sessionmaker, raid.id)
    response = await client.post(f"{SYNC_PATH}/events", json=event)
    assert response.status_code == 204
    after = await _raid_snapshot(db_sessionmaker, raid.id)
    assert after["updated_at"] == before["updated_at"]


async def test_real_discord_edit_updates_fields_and_strips_footer(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid = await _seed_raid(db_sessionmaker, title="Naxxramas")
    event = await _ack(client, raid.id, 555_005)
    new_starts_at = datetime.now(UTC) + timedelta(days=2)
    edited = dict(event)
    edited["name"] = "Naxxramas (rescheduled)"
    edited["description"] = f"Bring frost resist gear\n\n{FOOTER_HEADER}\nstale footer content"
    edited["starts_at"] = new_starts_at.isoformat()
    response = await client.post(f"{SYNC_PATH}/events", json=edited)
    assert response.status_code == 204
    snapshot = await _raid_snapshot(db_sessionmaker, raid.id)
    assert snapshot["title"] == "Naxxramas (rescheduled)"
    assert snapshot["notes"] == "Bring frost resist gear"
    assert snapshot["starts_at"] == new_starts_at


async def test_unknown_discord_event_creates_raid_with_null_size_and_empty_instance(
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
        raid = (await session.execute(select(Raid).where(Raid.discord_event_id == 555_006))).scalar_one()
        assert raid.size is None
        assert raid.instance == ""
        assert raid.title == "Impromptu Dungeon Run"
        assert raid.notes == "Just vibes"
        assert raid.status == "scheduled"


async def test_adoption_via_footer_link_links_instead_of_duplicating(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid = await _seed_raid(db_sessionmaker, title="The Deadmines")
    push = await _push_for(client, raid.id)
    before_count = await _raid_count(db_sessionmaker)
    event = _event_from_push(push, 555_007)
    response = await client.post(f"{SYNC_PATH}/events", json=event)
    assert response.status_code == 204
    after_count = await _raid_count(db_sessionmaker)
    assert after_count == before_count
    snapshot = await _raid_snapshot(db_sessionmaker, raid.id)
    assert snapshot["discord_event_id"] == 555_007


async def test_discord_delete_cancels_scheduled_raid_and_unlinks(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid = await _seed_raid(db_sessionmaker, title="Stratholme")
    event = await _ack(client, raid.id, 555_008)
    response = await client.delete(f"{SYNC_PATH}/events/{event['id']}")
    assert response.status_code == 204
    snapshot = await _raid_snapshot(db_sessionmaker, raid.id)
    assert snapshot["status"] == "cancelled"
    assert snapshot["discord_event_id"] is None
    assert snapshot["discord_pushed_hash"] is None
    assert snapshot["discord_seen_hash"] is None


async def test_reconcile_treats_missing_linked_event_as_deleted_and_drops_stale_tombstones(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    kept_raid = await _seed_raid(db_sessionmaker, title="Uldaman")
    kept_event = await _ack(client, kept_raid.id, 555_009)
    missing_raid = await _seed_raid(db_sessionmaker, title="Maraudon")
    await _ack(client, missing_raid.id, 555_010)
    async with db_sessionmaker() as session:
        session.add(DiscordEventTombstone(discord_event_id=555_011))
        await session.commit()

    response = await client.post(f"{SYNC_PATH}/reconcile", json={"events": [kept_event]})
    assert response.status_code == 204

    missing_snapshot = await _raid_snapshot(db_sessionmaker, missing_raid.id)
    assert missing_snapshot["status"] == "cancelled"
    assert missing_snapshot["discord_event_id"] is None

    kept_snapshot = await _raid_snapshot(db_sessionmaker, kept_raid.id)
    assert kept_snapshot["discord_event_id"] == 555_009

    assert await _tombstone_ids(db_sessionmaker) == set()


async def test_site_delete_of_linked_raid_produces_tombstone(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid = await _seed_raid(db_sessionmaker, title="Scholomance", discord_event_id=555_012)
    async with db_sessionmaker() as session:
        await session.execute(delete(Raid).where(Raid.id == raid.id))
        session.add(DiscordEventTombstone(discord_event_id=555_012))
        await session.commit()
    pending = (await client.get(f"{SYNC_PATH}/")).json()
    assert 555_012 in pending["deletions"]


async def test_ack_for_deleted_raid_tombstones_the_event(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid = await _seed_raid(db_sessionmaker, title="Razorfen Kraul")
    push = await _push_for(client, raid.id)
    event = _event_from_push(push, 555_013)
    async with db_sessionmaker() as session:
        await session.execute(delete(Raid).where(Raid.id == raid.id))
        await session.commit()
    response = await client.post(f"{SYNC_PATH}/{raid.id}/ack", json={"push_hash": push["push_hash"], "event": event})
    assert response.status_code == 204
    assert 555_013 in await _tombstone_ids(db_sessionmaker)


async def test_wrong_guild_id_is_404(client: AsyncTestClient) -> None:
    response = await client.get(f"/api/guilds/{GUILD_ID + 1}/raid-sync/")
    assert response.status_code == 404


async def test_description_stays_within_limit_with_long_notes(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid = await _seed_raid(db_sessionmaker, title="Molten Core", notes="x" * 2000)
    push = await _push_for(client, raid.id)
    assert len(push["description"]) <= 1000
    assert push["description"].endswith(f"Sign up: http://localhost:8000/raids/event/?id={raid.id}")
    assert FOOTER_HEADER in push["description"]
