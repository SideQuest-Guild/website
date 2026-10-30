from datetime import UTC, datetime, timedelta

import pytest

from sidequest_api.domain.heroes.services import HeroesService
from sidequest_common.models import EventSignup, GuildEvent, Member, MemberBadge, MemberLevel
from sidequest_common.settings import WebSettings
from tests.conftest import GUILD_ID
from tests.unit.api.conftest import login_as


def _event(**overrides: object) -> GuildEvent:
    base: dict[str, object] = {
        "kind": "raid",
        "title": "Molten Core",
        "location": "",
        "starts_at": datetime.now(UTC) - timedelta(days=1),
        "status": "completed",
    }
    base.update(overrides)
    return GuildEvent(**base)


def _signed(event: GuildEvent, member: Member, **overrides: object) -> EventSignup:
    base: dict[str, object] = {"event_id": event.id, "member_id": member.id, "status": "signed"}
    base.update(overrides)
    return EventSignup(**base)


async def test_anonymous_request_is_401(client) -> None:
    client.headers.pop("X-API-Key")
    response = await client.get("/api/heroes")
    assert response.status_code == 401


async def test_bot_key_can_read_leaderboard(client) -> None:
    response = await client.get("/api/heroes")
    assert response.status_code == 200
    assert response.json()["season_id"] == "season-one"


async def test_signed_in_member_can_read_leaderboard(member_client, discord_state) -> None:
    login_response = await login_as(member_client, discord_state, discord_id=4001, roles=[])
    assert login_response.status_code == 302, login_response.text
    response = await member_client.get("/api/heroes")
    assert response.status_code == 200


async def test_leaderboard_orders_by_ep_descending(client, db_sessionmaker) -> None:
    async with db_sessionmaker() as session:
        alice = Member(discord_id=5001, username="alice", is_guild_member=True)
        bob = Member(discord_id=5002, username="bob", is_guild_member=True)
        session.add_all([alice, bob])
        await session.flush()
        raid = _event(kind="raid")
        dungeon = _event(kind="dungeon", starts_at=datetime.now(UTC) - timedelta(days=2))
        session.add_all([raid, dungeon])
        await session.flush()
        session.add_all(
            [
                _signed(raid, alice),
                _signed(dungeon, alice),
                _signed(raid, bob),
            ]
        )
        await session.commit()

    response = await client.get("/api/heroes", params={"season": "all"})
    assert response.status_code == 200
    body = response.json()
    assert [row["display_name"] for row in body["rows"]] == ["alice", "bob"]
    assert body["rows"][0]["ep"] == 15  # raid (10) + dungeon (5)
    assert body["rows"][0]["raids_attended"] == 1
    assert body["rows"][1]["ep"] == 10


async def test_leaderboard_excludes_members_with_zero_ep(client, db_sessionmaker) -> None:
    async with db_sessionmaker() as session:
        session.add(Member(discord_id=5101, username="bystander", is_guild_member=True))
        await session.commit()

    response = await client.get("/api/heroes", params={"season": "all"})
    assert response.status_code == 200
    assert response.json()["rows"] == []


async def test_leaderboard_month_window_excludes_events_outside_this_month(client, db_sessionmaker) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=5201, username="veteran", is_guild_member=True)
        session.add(member)
        await session.flush()
        old_event = _event(starts_at=datetime.now(UTC) - timedelta(days=400))
        session.add(old_event)
        await session.flush()
        session.add(_signed(old_event, member))
        await session.commit()

    response = await client.get("/api/heroes", params={"season": "month"})
    assert response.status_code == 200
    assert response.json()["rows"] == []
    assert response.json()["season_id"] == "month"


async def test_profile_includes_stats_class_badges_and_rank(client, db_sessionmaker) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=5301, username="hero", is_guild_member=True)
        session.add(member)
        await session.flush()
        raid = _event(kind="raid", title="Blackwing Lair")
        session.add(raid)
        await session.flush()
        session.add(_signed(raid, member, character="Thrall", wow_class="shaman", role="healer"))
        session.add(MemberLevel(guild_id=GUILD_ID, user_id=member.discord_id, xp=0, level=3))
        session.add(MemberBadge(member_id=member.id, badge_id="first_raid", earned_at=datetime.now(UTC)))
        await session.commit()
        member_id = member.id

    response = await client.get(f"/api/heroes/{member_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["wow_class"] == "shaman"
    assert body["chat_level"] == 3
    assert body["all_time"]["raids_attended"] == 1
    assert body["all_time"]["ep"] == 10
    assert len(body["recent_events"]) == 1
    assert body["recent_events"][0]["title"] == "Blackwing Lair"
    assert [b["id"] for b in body["badges"]] == ["first_raid"]


async def test_profile_404_for_unknown_member(client) -> None:
    response = await client.get("/api/heroes/999999")
    assert response.status_code == 404


async def test_attendance_rate_counts_only_completed_events(client, db_sessionmaker) -> None:
    async with db_sessionmaker() as session:
        member = Member(discord_id=5401, username="half-timer", is_guild_member=True)
        session.add(member)
        await session.flush()
        attended = _event(kind="raid")
        missed = _event(kind="raid", status="scheduled", starts_at=datetime.now(UTC) - timedelta(days=3))
        session.add_all([attended, missed])
        await session.flush()
        session.add(_signed(attended, member))
        session.add(_signed(missed, member, status="absent"))
        await session.commit()
        member_id = member.id

    response = await client.get(f"/api/heroes/{member_id}")
    assert response.status_code == 200
    rate = response.json()["all_time"]["attendance_rate"]
    assert rate == pytest.approx(0.5)


async def test_rank_and_season_window_respect_season_start(db_sessionmaker) -> None:
    """Season-one starts 2026-11-04; an explicit ``now`` keeps this independent of the real wall clock."""
    reference = datetime(2027, 1, 15, tzinfo=UTC)
    async with db_sessionmaker() as session:
        hero = Member(discord_id=5501, username="hero", is_guild_member=True)
        bystander = Member(discord_id=5502, username="bystander", is_guild_member=True)
        session.add_all([hero, bystander])
        await session.flush()
        in_season = _event(kind="raid", starts_at=datetime(2026, 11, 10, tzinfo=UTC))
        before_season = _event(kind="raid", starts_at=datetime(2026, 10, 1, tzinfo=UTC))
        session.add_all([in_season, before_season])
        await session.flush()
        session.add(_signed(in_season, hero))
        session.add(_signed(before_season, bystander))
        await session.commit()

        service = HeroesService(session, WebSettings(_env_file=None))
        profile = await service.get_profile(hero.id, now=reference)
        assert profile.rank == 1
        assert profile.seasons["season-one"].raids_attended == 1
        assert profile.all_time.raids_attended == 1

        bystander_profile = await service.get_profile(bystander.id, now=reference)
        assert bystander_profile.rank is None
        assert bystander_profile.seasons["season-one"].raids_attended == 0
        assert bystander_profile.all_time.raids_attended == 1
