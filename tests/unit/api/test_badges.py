from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sidequest_common.models import EventSignup, GuildEvent, Member, MemberBadge, MemberLevel
from sidequest_common.schemas.badges import CHATTERBOX_LEVEL, PERFECT_MONTH_MIN_RAIDS, RAID_REGULAR_THRESHOLD
from tests.conftest import GUILD_ID

BADGES_PATH = f"/api/guilds/{GUILD_ID}/badges"


def _event(**overrides: object) -> GuildEvent:
    base: dict[str, object] = {
        "kind": "raid",
        "title": "Raid Night",
        "location": "",
        "starts_at": datetime.now(UTC) - timedelta(days=1),
        "status": "completed",
    }
    base.update(overrides)
    return GuildEvent(**base)


def _signed(event: GuildEvent, member: Member) -> EventSignup:
    return EventSignup(event_id=event.id, member_id=member.id, status="signed")


async def test_wrong_guild_id_is_404(client) -> None:
    response = await client.get(f"/api/guilds/{GUILD_ID + 1}/badges/sync")
    assert response.status_code == 404


async def test_requires_api_key(client) -> None:
    client.headers.pop("X-API-Key")
    response = await client.get(f"{BADGES_PATH}/sync")
    assert response.status_code == 401


async def test_sync_awards_first_steps_and_first_raid_idempotently(client, db_sessionmaker) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=6001, username="newbie", is_guild_member=True)
        session.add(member)
        await session.flush()
        raid = _event()
        session.add(raid)
        await session.flush()
        session.add(_signed(raid, member))
        await session.commit()
        discord_id = member.discord_id

    first = await client.get(f"{BADGES_PATH}/sync")
    assert first.status_code == 200
    body = first.json()
    role_state = {row["discord_id"]: row["badge_ids"] for row in body["role_state"]}
    assert set(role_state[discord_id]) == {"first_steps", "first_raid"}
    pending_ids = {p["badge_id"] for p in body["pending"]}
    assert {"first_steps", "first_raid"} <= pending_ids

    # Ack both, then a second sync with no new activity reports no (re-)pending announcements and no duplicate rows.
    for badge_id in ("first_steps", "first_raid"):
        ack = await client.post(f"{BADGES_PATH}/ack", json={"discord_id": discord_id, "badge_id": badge_id})
        assert ack.status_code == 204
    second = await client.get(f"{BADGES_PATH}/sync")
    assert second.status_code == 200
    second_body = second.json()
    second_role_state = {row["discord_id"]: row["badge_ids"] for row in second_body["role_state"]}
    assert set(second_role_state[discord_id]) == {"first_steps", "first_raid"}
    second_pending_ids = {p["badge_id"] for p in second_body["pending"]}
    assert "first_steps" not in second_pending_ids
    assert "first_raid" not in second_pending_ids


async def test_sync_awards_raid_regular_at_threshold(client, db_sessionmaker) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=6101, username="regular", is_guild_member=True)
        session.add(member)
        await session.flush()
        for i in range(RAID_REGULAR_THRESHOLD):
            raid = _event(starts_at=datetime.now(UTC) - timedelta(days=i + 1))
            session.add(raid)
            await session.flush()
            session.add(_signed(raid, member))
        await session.commit()
        discord_id = member.discord_id

    response = await client.get(f"{BADGES_PATH}/sync")
    assert response.status_code == 200
    role_state = {row["discord_id"]: row["badge_ids"] for row in response.json()["role_state"]}
    assert "raid_regular" in role_state[discord_id]


async def test_sync_awards_chatterbox_at_level(client, db_sessionmaker) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=6201, username="talker", is_guild_member=True)
        session.add(member)
        await session.flush()
        session.add(MemberLevel(guild_id=GUILD_ID, user_id=member.discord_id, xp=0, level=CHATTERBOX_LEVEL))
        await session.commit()
        discord_id = member.discord_id

    response = await client.get(f"{BADGES_PATH}/sync")
    assert response.status_code == 200
    role_state = {row["discord_id"]: row["badge_ids"] for row in response.json()["role_state"]}
    assert "chatterbox" in role_state[discord_id]


async def test_top_helper_moves_to_new_winner(client, db_sessionmaker) -> None:
    now = datetime.now(UTC)
    last_month = now.replace(day=1) - timedelta(days=5)
    async with db_sessionmaker() as session:
        alice = Member(discord_id=6301, username="alice", is_guild_member=True)
        bob = Member(discord_id=6302, username="bob", is_guild_member=True)
        session.add_all([alice, bob])
        await session.flush()
        for i in range(3):
            dungeon = _event(kind="dungeon", starts_at=last_month - timedelta(days=i))
            session.add(dungeon)
            await session.flush()
            session.add(_signed(dungeon, alice))
        session.add(MemberBadge(member_id=bob.id, badge_id="top_helper", earned_at=now - timedelta(days=40)))
        await session.commit()
        alice_discord = alice.discord_id

    response = await client.get(f"{BADGES_PATH}/sync")
    assert response.status_code == 200
    role_state = {row["discord_id"]: row["badge_ids"] for row in response.json()["role_state"]}
    assert "top_helper" in role_state[alice_discord]
    assert all("top_helper" not in badges for discord_id, badges in role_state.items() if discord_id != alice_discord)


async def test_ack_marks_announced(client, db_sessionmaker) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=6401, username="acker", is_guild_member=True)
        session.add(member)
        await session.flush()
        session.add(MemberBadge(member_id=member.id, badge_id="chatterbox", earned_at=datetime.now(UTC)))
        await session.commit()
        discord_id = member.discord_id

    response = await client.post(f"{BADGES_PATH}/ack", json={"discord_id": discord_id, "badge_id": "chatterbox"})
    assert response.status_code == 204

    sync = await client.get(f"{BADGES_PATH}/sync")
    pending_ids = {p["badge_id"] for p in sync.json()["pending"]}
    assert "chatterbox" not in pending_ids


async def test_perfect_month_not_awarded_for_the_in_progress_current_month(client, db_sessionmaker) -> None:
    """Four attended raids early in the still-running current month must not award this irreversible badge yet:
    more raids could still be scheduled, and the member could miss the rest of the month.
    """
    async with db_sessionmaker() as session:
        member = Member(discord_id=6301, username="eager", is_guild_member=True)
        session.add(member)
        await session.flush()
        now = datetime.now(UTC)
        for i in range(PERFECT_MONTH_MIN_RAIDS):
            raid = _event(starts_at=now - timedelta(hours=i + 1))
            session.add(raid)
            await session.flush()
            session.add(_signed(raid, member))
        await session.commit()
        discord_id = member.discord_id

    response = await client.get(f"{BADGES_PATH}/sync")
    assert response.status_code == 200
    role_state = {row["discord_id"]: row["badge_ids"] for row in response.json()["role_state"]}
    assert "perfect_month" not in role_state.get(discord_id, [])


async def test_perfect_month_awarded_for_a_completed_month(client, db_sessionmaker) -> None:
    """Attending every raid in a calendar month that's entirely in the past (America/Chicago) awards the badge."""
    async with db_sessionmaker() as session:
        member = Member(discord_id=6302, username="dedicated", is_guild_member=True)
        session.add(member)
        await session.flush()
        now_chicago = datetime.now(UTC).astimezone(ZoneInfo("America/Chicago"))
        month_start = now_chicago.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = month_start - timedelta(seconds=1)
        for i in range(PERFECT_MONTH_MIN_RAIDS):
            raid = _event(starts_at=(last_month_end - timedelta(days=i)).astimezone(UTC))
            session.add(raid)
            await session.flush()
            session.add(_signed(raid, member))
        await session.commit()
        discord_id = member.discord_id

    response = await client.get(f"{BADGES_PATH}/sync")
    assert response.status_code == 200
    role_state = {row["discord_id"]: row["badge_ids"] for row in response.json()["role_state"]}
    assert "perfect_month" in role_state[discord_id]
