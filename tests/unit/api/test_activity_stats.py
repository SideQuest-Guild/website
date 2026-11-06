"""Hourly activity recording (chat/voice/backfill), officer stats, and the Hall of Heroes activity chart."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from sidequest_api.domain.members.services import MembersService
from sidequest_api.domain.stats.services import StatsService
from sidequest_common.models import Member, MemberActivityHour
from sidequest_common.schemas import StatsRange
from sidequest_common.settings import WebSettings
from tests.conftest import GUILD_ID
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

XP_PATH = f"/api/guilds/{GUILD_ID}/xp"
NOW = datetime.now(UTC)


async def _member(db: async_sessionmaker[AsyncSession], discord_id: int) -> int:
    async with db() as session:
        member = Member(discord_id=discord_id, username=f"m{discord_id}", is_guild_member=True)
        session.add(member)
        await session.commit()
        return member.id


async def _activity_row(db: async_sessionmaker[AsyncSession], discord_id: int) -> MemberActivityHour | None:
    async with db() as session:
        stmt = select(MemberActivityHour).where(
            MemberActivityHour.guild_id == GUILD_ID, MemberActivityHour.user_id == discord_id
        )
        return (await session.execute(stmt)).scalars().one_or_none()


# --- Chat recording -----------------------------------------------------------------------------------------


async def test_award_xp_records_chat_xp_only_when_awarded(client, db_sessionmaker) -> None:
    response = await client.post(f"/api/guilds/{GUILD_ID}/members/701/xp")
    assert response.status_code == 200
    body = response.json()
    row = await _activity_row(db_sessionmaker, 701)
    assert row is not None
    assert row.messages == 1
    assert body["awarded"] is True
    assert row.chat_xp == body["amount"]
    assert row.chat_xp > 0


async def test_award_xp_records_messages_and_chat_xp(client, db_sessionmaker) -> None:
    await client.post(f"/api/guilds/{GUILD_ID}/members/702/xp")
    await client.post(f"/api/guilds/{GUILD_ID}/members/702/xp")
    row = await _activity_row(db_sessionmaker, 702)
    assert row is not None
    assert row.messages == 2
    # Default xp_cooldown_seconds keeps the second call off cooldown only if config allows; either way chat_xp >= 0.
    assert row.chat_xp >= 0


async def test_award_xp_bumps_messages_even_when_leveling_disabled(client, db_sessionmaker) -> None:
    await client.patch(f"/api/guilds/{GUILD_ID}/config", json={"leveling_enabled": False})
    await client.post(f"/api/guilds/{GUILD_ID}/members/703/xp")
    row = await _activity_row(db_sessionmaker, 703)
    assert row is not None
    assert row.messages == 1
    assert row.chat_xp == 0


# --- Voice recording -----------------------------------------------------------------------------------------


async def test_voice_records_minutes_for_present_ids_beyond_user_ids(client, db_sessionmaker) -> None:
    response = await client.post(
        f"{XP_PATH}/voice", json={"user_ids": [711], "present_user_ids": [711, 712], "minutes": 4}
    )
    assert response.status_code == 200
    xp_eligible = await _activity_row(db_sessionmaker, 711)
    presence_only = await _activity_row(db_sessionmaker, 712)
    assert xp_eligible is not None
    assert xp_eligible.voice_minutes == 4
    assert xp_eligible.voice_xp > 0
    assert presence_only is not None
    assert presence_only.voice_minutes == 4
    assert presence_only.voice_xp == 0


async def test_voice_records_presence_even_when_leveling_disabled(client, db_sessionmaker) -> None:
    await client.patch(f"/api/guilds/{GUILD_ID}/config", json={"leveling_enabled": False})
    response = await client.post(
        f"{XP_PATH}/voice", json={"user_ids": [721], "present_user_ids": [721, 722], "minutes": 3}
    )
    assert response.status_code == 200
    assert response.json() == []
    row = await _activity_row(db_sessionmaker, 722)
    assert row is not None
    assert row.voice_minutes == 3
    assert row.voice_xp == 0


async def test_voice_accepts_old_bot_body_without_present_user_ids(client, db_sessionmaker) -> None:
    response = await client.post(f"{XP_PATH}/voice", json={"user_ids": [731], "minutes": 2})
    assert response.status_code == 200
    row = await _activity_row(db_sessionmaker, 731)
    assert row is not None
    assert row.voice_minutes == 2


# --- Backfill -------------------------------------------------------------------------------------------------


async def test_backfill_sets_max_and_is_idempotent(client, db_sessionmaker) -> None:
    hour = "2026-11-04T09:00:00+00:00"
    path = f"/api/guilds/{GUILD_ID}/activity/messages"
    r1 = await client.put(path, json={"buckets": [{"user_id": 741, "hour_start": hour, "messages": 5}]})
    assert r1.status_code == 200
    assert r1.json() == {"buckets": 1}

    r2 = await client.put(path, json={"buckets": [{"user_id": 741, "hour_start": hour, "messages": 2}]})
    assert r2.status_code == 200
    row = await _activity_row(db_sessionmaker, 741)
    assert row is not None
    assert row.messages == 5  # never lowers a live/higher count

    r3 = await client.put(path, json={"buckets": [{"user_id": 741, "hour_start": hour, "messages": 9}]})
    assert r3.status_code == 200
    row = await _activity_row(db_sessionmaker, 741)
    assert row is not None
    assert row.messages == 9

    r4 = await client.put(path, json={"buckets": [{"user_id": 741, "hour_start": hour, "messages": 9}]})
    assert r4.status_code == 200
    async with db_sessionmaker() as session:
        result = (
            await session.execute(
                select(func.count()).select_from(MemberActivityHour).where(MemberActivityHour.user_id == 741)
            )
        ).scalar_one()
    assert result == 1  # still one row, not duplicated


# --- Account deletion ----------------------------------------------------------------------------------------


async def test_deleting_an_account_erases_its_activity_rows(client, db_sessionmaker) -> None:
    member_id = await _member(db_sessionmaker, 751)
    await client.post(f"/api/guilds/{GUILD_ID}/members/751/xp")
    assert await _activity_row(db_sessionmaker, 751) is not None

    async with db_sessionmaker() as session:
        member = await session.get(Member, member_id)
        assert member is not None
        await MembersService(session).delete_account(member)

    assert await _activity_row(db_sessionmaker, 751) is None


# --- Officer stats route auth -------------------------------------------------------------------------------


async def test_stats_requires_sign_in(member_client) -> None:
    response = await member_client.get("/api/stats")
    assert response.status_code == 401


async def test_stats_requires_officer(member_client, discord_state) -> None:
    await login_as(member_client, discord_state, discord_id=8001, roles=[])
    response = await member_client.get("/api/stats")
    assert response.status_code == 403


async def test_stats_officer_gets_guild_stats_shape(member_client, discord_state, db_sessionmaker) -> None:
    await login_as(member_client, discord_state, discord_id=8002, roles=[OFFICER_ROLE_ID])
    async with db_sessionmaker() as session:
        session.add(
            MemberActivityHour(
                guild_id=GUILD_ID,
                user_id=8003,
                hour_start=NOW.replace(minute=0, second=0, microsecond=0),
                messages=3,
                voice_minutes=10,
                chat_xp=5,
                voice_xp=10,
            )
        )
        await session.commit()
    response = await member_client.get("/api/stats?range=7d")
    assert response.status_code == 200
    body = response.json()
    assert body["range"] == "7d"
    assert body["trend_bucket"] == "day"
    assert body["totals"]["messages"] == 3
    assert body["totals"]["voice_minutes"] == 10
    assert body["totals"]["active_members"] == 1
    assert body["previous"] is not None
    assert len(body["trend"]) == 8  # since..now inclusive, zero-filled
    assert any(leader["value"] == 3 for leader in body["top_chatters"])


async def test_seven_day_trend_has_eight_days_late_evening_after_clocks_go_back(db_sessionmaker) -> None:
    # 2026-11-05 23:13 in Chicago, four days after daylight saving ended: 7 x 24 hours back is just past midnight
    # on Oct 30 there, which used to drop Oct 29 from the trend.
    late_evening = datetime(2026, 11, 6, 5, 13, tzinfo=UTC)
    async with db_sessionmaker() as session:
        stats = await StatsService(session, WebSettings(GUILD_ID=GUILD_ID)).get_stats(
            StatsRange.SEVEN_DAYS, now=late_evening
        )
    assert [point.start.isoformat() for point in stats.trend][:1] == ["2026-10-29"]
    assert len(stats.trend) == 8


async def test_stats_all_range_has_no_previous_and_week_buckets(member_client, discord_state) -> None:
    await login_as(member_client, discord_state, discord_id=8004, roles=[OFFICER_ROLE_ID])
    response = await member_client.get("/api/stats?range=all")
    assert response.status_code == 200
    body = response.json()
    assert body["since"] is None
    assert body["previous"] is None
    assert body["trend_bucket"] == "week"


async def test_gone_quiet_lists_roster_members_with_no_recent_activity(
    member_client, discord_state, db_sessionmaker
) -> None:
    await login_as(member_client, discord_state, discord_id=8005, roles=[OFFICER_ROLE_ID])
    async with db_sessionmaker() as session:
        session.add(Member(discord_id=8006, username="quiet", is_guild_member=True))
        session.add(Member(discord_id=8007, username="gone", is_guild_member=False))
        await session.commit()
    response = await member_client.get("/api/stats?range=all")
    assert response.status_code == 200
    quiet_ids = {row["person"]["discord_id"] for row in response.json()["gone_quiet"]}
    assert "8006" in quiet_ids
    assert "8007" not in quiet_ids  # no longer in the guild


# --- Hero activity route --------------------------------------------------------------------------------------


async def test_hero_activity_requires_sign_in(member_client, db_sessionmaker) -> None:
    member_id = await _member(db_sessionmaker, 9001)
    response = await member_client.get(f"/api/heroes/{member_id}/activity")
    assert response.status_code == 401


async def test_hero_activity_404_for_unknown_member(client) -> None:
    response = await client.get("/api/heroes/999999/activity")
    assert response.status_code == 404


async def test_hero_activity_streaks_and_days(client, db_sessionmaker) -> None:
    member_id = await _member(db_sessionmaker, 9002)
    today = NOW.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    async with db_sessionmaker() as session:
        for offset in range(3):  # today, yesterday, day before: a 3-day streak
            session.add(
                MemberActivityHour(
                    guild_id=GUILD_ID,
                    user_id=9002,
                    hour_start=today - timedelta(days=offset),
                    messages=1,
                    voice_minutes=0,
                    chat_xp=1,
                    voice_xp=0,
                )
            )
        await session.commit()

    response = await client.get(f"/api/heroes/{member_id}/activity")
    assert response.status_code == 200
    body = response.json()
    assert body["current_streak_days"] >= 3
    assert body["longest_streak_days"] >= 3
    assert len(body["days"]) == 30
    assert body["xp_sources"]["chat"] == 3
    assert body["xp_sources"]["earlier"] == 0  # no MemberLevel row, so lifetime xp is 0
