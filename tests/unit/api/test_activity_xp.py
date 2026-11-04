"""XP from voice, attended events and #lfg groups: who gets paid, how much, and only once."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select

from sidequest_api.domain.members.services import MembersService
from sidequest_common.models import EventSignup, GroupSession, GroupSessionMember, GuildEvent, Member, XPGrant
from sidequest_common.schemas import EVENT_XP, GROUP_XP, VOICE_XP_PER_MINUTE, XP_LOOKBACK_DAYS
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

XP_PATH = f"/api/guilds/{GUILD_ID}/xp"
NOW = datetime.now(UTC)
NO_XP_ROLE = 9_999


async def _activity(client: AsyncTestClient[Litestar]) -> list[dict[str, Any]]:
    response = await client.post(f"{XP_PATH}/activity")
    assert response.status_code == 200
    return response.json()["grants"]


async def _xp(client: AsyncTestClient[Litestar], user_id: int) -> int:
    response = await client.get(f"/api/guilds/{GUILD_ID}/members/{user_id}/rank")
    return response.json()["xp"]


async def _member(db: async_sessionmaker[AsyncSession], discord_id: int, roles: list[int] | None = None) -> int:
    async with db() as session:
        member = Member(discord_id=discord_id, username=f"m{discord_id}", is_guild_member=True, roles=roles or [])
        session.add(member)
        await session.commit()
        return member.id


async def _event(
    db: async_sessionmaker[AsyncSession],
    signups: Sequence[tuple[int, str, bool | None]],
    *,
    starts_at: datetime,
    attendance_taken: bool,
    status: str = "completed",
) -> UUID:
    """An event with ``(member id, signup status, attended)`` sign-ups."""
    async with db() as session:
        event = GuildEvent(
            kind="raid",
            title="Raid",
            location="",
            starts_at=starts_at,
            status=status,
            attendance_taken_at=starts_at + timedelta(hours=3) if attendance_taken else None,
        )
        session.add(event)
        await session.flush()
        for member_id, signup_status, attended in signups:
            session.add(EventSignup(event_id=event.id, member_id=member_id, status=signup_status, attended=attended))
        await session.commit()
        return event.id


async def _group(
    db: async_sessionmaker[AsyncSession],
    minutes: dict[int, int],
    *,
    ended_at: datetime | None,
    peak_size: int = 2,
    grouped_minutes: int = 30,
) -> UUID:
    async with db() as session:
        group = GroupSession(
            discord_channel_id=int(NOW.timestamp() * 1000) + len(minutes) + peak_size + grouped_minutes,
            channel_name="dungeon-1",
            kind="dungeon",
            needs=[],
            creator_discord_id=next(iter(minutes)),
            owner_discord_id=next(iter(minutes)),
            started_at=(ended_at or NOW) - timedelta(hours=1),
            ended_at=ended_at,
            peak_size=peak_size,
            grouped_minutes=grouped_minutes,
        )
        session.add(group)
        await session.flush()
        for discord_id, spent in minutes.items():
            session.add(GroupSessionMember(session_id=group.id, discord_id=discord_id, display_name="x", minutes=spent))
        await session.commit()
        return group.id


async def test_voice_xp_goes_to_each_listed_member_once_per_call(client: AsyncTestClient[Litestar]) -> None:
    response = await client.post(f"{XP_PATH}/voice", json={"user_ids": [501, 502, 501], "minutes": 2})

    assert response.status_code == 200
    grants = response.json()
    assert sorted(g["user_id"] for g in grants) == [501, 502]
    assert {g["amount"] for g in grants} == {2 * VOICE_XP_PER_MINUTE}
    assert {g["source"] for g in grants} == {"voice"}
    assert await _xp(client, 501) == 2 * VOICE_XP_PER_MINUTE


async def test_voice_xp_leaves_the_chat_cooldown_and_message_count_alone(client: AsyncTestClient[Litestar]) -> None:
    await client.patch(f"/api/guilds/{GUILD_ID}/config", json={"xp_min": 10, "xp_max": 10, "xp_cooldown_seconds": 60})
    await client.post(f"{XP_PATH}/voice", json={"user_ids": [503]})

    chat = (await client.post(f"/api/guilds/{GUILD_ID}/members/503/xp")).json()

    assert chat["awarded"] is True
    rank = (await client.get(f"/api/guilds/{GUILD_ID}/members/503/rank")).json()
    assert rank["message_count"] == 1
    assert rank["xp"] == VOICE_XP_PER_MINUTE + 10


async def test_voice_xp_reports_level_ups_and_level_roles(client: AsyncTestClient[Litestar]) -> None:
    await client.put(f"/api/guilds/{GUILD_ID}/level-roles/1", json={"role_id": 7001})
    await client.put(f"/api/guilds/{GUILD_ID}/members/504/xp", json={"xp": 100 - VOICE_XP_PER_MINUTE})

    (grant,) = (await client.post(f"{XP_PATH}/voice", json={"user_ids": [504]})).json()

    assert grant["leveled_up"] is True
    assert grant["level"] == 1
    assert grant["earned_role_ids"] == [7001]


async def test_nothing_is_paid_while_leveling_is_off(client, db_sessionmaker) -> None:
    member_id = await _member(db_sessionmaker, 505)
    await _event(
        db_sessionmaker, [(member_id, "signed", True)], starts_at=NOW - timedelta(hours=2), attendance_taken=True
    )
    await client.patch(f"/api/guilds/{GUILD_ID}/config", json={"leveling_enabled": False})

    assert (await client.post(f"{XP_PATH}/voice", json={"user_ids": [505]})).json() == []
    assert await _activity(client) == []

    await client.patch(f"/api/guilds/{GUILD_ID}/config", json={"leveling_enabled": True})
    assert [g["user_id"] for g in await _activity(client)] == [505]


async def test_events_pay_who_came_once(client, db_sessionmaker) -> None:
    came, no_show, maybe = [await _member(db_sessionmaker, discord_id) for discord_id in (511, 512, 513)]
    await _event(
        db_sessionmaker,
        [(came, "signed", True), (no_show, "signed", False), (maybe, "tentative", True)],
        starts_at=NOW - timedelta(hours=4),
        attendance_taken=True,
    )

    first = await _activity(client)
    second = await _activity(client)

    assert sorted(g["user_id"] for g in first) == [511, 513]
    assert {(g["source"], g["amount"]) for g in first} == {("event", EVENT_XP)}
    assert second == []
    assert await _xp(client, 511) == EVENT_XP


async def test_untaken_attendance_pays_sign_ups_only_after_a_day(client, db_sessionmaker) -> None:
    member_id = await _member(db_sessionmaker, 521)
    await _event(
        db_sessionmaker, [(member_id, "signed", None)], starts_at=NOW - timedelta(hours=3), attendance_taken=False
    )
    assert await _activity(client) == []

    await _event(
        db_sessionmaker, [(member_id, "signed", None)], starts_at=NOW - timedelta(hours=30), attendance_taken=False
    )
    assert [g["user_id"] for g in await _activity(client)] == [521]


async def test_cancelled_future_and_old_events_pay_nothing(client, db_sessionmaker) -> None:
    member_id = await _member(db_sessionmaker, 531)
    came = [(member_id, "signed", True)]
    await _event(db_sessionmaker, came, starts_at=NOW - timedelta(hours=5), attendance_taken=True, status="cancelled")
    await _event(db_sessionmaker, came, starts_at=NOW + timedelta(hours=5), attendance_taken=True, status="scheduled")
    old = NOW - timedelta(days=XP_LOOKBACK_DAYS + 1)
    await _event(db_sessionmaker, came, starts_at=old, attendance_taken=True)

    assert await _activity(client) == []


async def test_groups_pay_members_who_stayed_ten_minutes_after_the_group_ends(client, db_sessionmaker) -> None:
    await _group(db_sessionmaker, {541: 25, 542: 4}, ended_at=NOW - timedelta(minutes=5))
    await _group(db_sessionmaker, {543: 60}, ended_at=None)  # still open
    await _group(db_sessionmaker, {544: 60}, ended_at=NOW, peak_size=1, grouped_minutes=0)  # nobody joined

    first = await _activity(client)

    assert [(g["user_id"], g["source"], g["amount"]) for g in first] == [(541, "group", GROUP_XP)]
    assert await _activity(client) == []


async def test_no_xp_roles_are_skipped(client, db_sessionmaker) -> None:
    await client.patch(f"/api/guilds/{GUILD_ID}/config", json={"no_xp_role_ids": [NO_XP_ROLE]})
    blocked = await _member(db_sessionmaker, 551, roles=[NO_XP_ROLE])
    await _event(
        db_sessionmaker, [(blocked, "signed", True)], starts_at=NOW - timedelta(hours=4), attendance_taken=True
    )

    assert await _activity(client) == []


async def test_activity_is_only_for_the_sidequest_server(client) -> None:
    response = await client.post(f"/api/guilds/{GUILD_ID + 1}/xp/activity")
    assert response.status_code == 404


async def test_deleting_an_account_erases_its_grants(client, db_sessionmaker) -> None:
    member_id = await _member(db_sessionmaker, 561)
    await _event(
        db_sessionmaker, [(member_id, "signed", True)], starts_at=NOW - timedelta(hours=4), attendance_taken=True
    )
    assert len(await _activity(client)) == 1

    async with db_sessionmaker() as session:
        member = await session.get(Member, member_id)
        assert member is not None
        await MembersService(session).delete_account(member)
        remaining = (await session.execute(select(func.count()).select_from(XPGrant))).scalar_one()
    assert remaining == 0
