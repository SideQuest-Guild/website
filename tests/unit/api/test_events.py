from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from sidequest_bot.api_client import API_KEY_HEADER
from sidequest_common.models import EventDiscordInterest, EventSignupActivity, GuildEvent
from tests.conftest import TEST_API_KEY
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _seed_event(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    title: str = "Molten Core",
    kind: str = "raid",
    starts_at: datetime | None = None,
    status: str = "scheduled",
    size: int = 40,
) -> str:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind=kind,
            title=title,
            location="Molten Core",
            starts_at=starts_at or (datetime.now(UTC) + timedelta(days=1)),
            size=size,
            status=status,
            notes=None,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return str(event.id)


def _signup_body(character: str = "Thrall", role: str = "dps", status: str = "signed") -> dict:
    return {"character": character, "class": "warrior", "role": role, "status": status, "comment": None}


async def test_non_member_gets_403_on_signup(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=2001, is_guild_member=False)
    response = await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body())
    assert response.status_code == 403


async def test_officer_only_endpoint_is_403_for_regular_member(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=2002, roles=[])
    response = await member_client.post(
        "/api/events",
        json={
            "kind": "raid",
            "title": "Onyxia's Lair",
            "location": "Onyxia",
            "starts_at": "2026-12-01T20:00:00Z",
            "size": 40,
            "notes": None,
        },
    )
    assert response.status_code == 403


async def test_signup_upsert_keeps_one_row(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=2003, roles=[])

    first = await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body(character="Thrall"))
    assert first.status_code == 200
    second = await member_client.put(
        f"/api/events/{event_id}/signup", json=_signup_body(character="Jaina", role="healer")
    )
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["class"] == "warrior"  # wire name per the contract, not the Python attribute

    detail = await member_client.get(f"/api/events/{event_id}")
    assert len(detail.json()["signups"]) == 1
    assert detail.json()["signups"][0]["character"] == "Jaina"
    assert detail.json()["signups"][0]["role"] == "healer"


async def test_counts_only_count_signed_signups(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)

    await login_as(member_client, discord_state, discord_id=2010, roles=[])
    await member_client.put(
        f"/api/events/{event_id}/signup", json=_signup_body(character="Tank1", role="tank", status="signed")
    )

    await login_as(member_client, discord_state, discord_id=2011, roles=[])
    await member_client.put(
        f"/api/events/{event_id}/signup", json=_signup_body(character="Heal1", role="healer", status="tentative")
    )

    await login_as(member_client, discord_state, discord_id=2012, roles=[])
    await member_client.put(
        f"/api/events/{event_id}/signup", json=_signup_body(character="Dps1", role="dps", status="absent")
    )

    response = await member_client.get(f"/api/events/{event_id}")
    counts = response.json()["counts"]
    assert counts == {"tank": 1, "healer": 0, "dps": 0, "signed": 1, "tentative": 1, "absent": 1, "interested": 0}


async def test_upcoming_and_past_split(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    now = datetime.now(UTC)
    future_id = await _seed_event(db_sessionmaker, title="Future Raid", starts_at=now + timedelta(days=3))
    past_id = await _seed_event(db_sessionmaker, title="Past Raid", starts_at=now - timedelta(days=3))
    # Marked done the same evening: still inside the upcoming look-back window, but it belongs in past.
    done_id = await _seed_event(
        db_sessionmaker, title="Done Tonight", starts_at=now - timedelta(hours=1), status="completed"
    )

    upcoming = await member_client.get("/api/events", params={"when": "upcoming"})
    past = await member_client.get("/api/events", params={"when": "past"})

    upcoming_ids = [event["id"] for event in upcoming.json()]
    past_ids = [event["id"] for event in past.json()]
    assert future_id in upcoming_ids
    assert future_id not in past_ids
    assert past_id in past_ids
    assert past_id not in upcoming_ids
    assert done_id in past_ids
    assert done_id not in upcoming_ids


async def test_kind_filter_only_returns_matching_events(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    raid_id = await _seed_event(db_sessionmaker, title="Molten Core", kind="raid")
    social_id = await _seed_event(db_sessionmaker, title="Guild Game Night", kind="social")

    raids = await member_client.get("/api/events", params={"when": "upcoming", "kind": "raid"})
    socials = await member_client.get("/api/events", params={"when": "upcoming", "kind": "social"})

    raid_ids = [event["id"] for event in raids.json()]
    social_ids = [event["id"] for event in socials.json()]
    assert raid_id in raid_ids
    assert social_id not in raid_ids
    assert social_id in social_ids
    assert raid_id not in social_ids


async def test_kind_filter_with_no_matches_returns_empty_list(member_client: AsyncTestClient) -> None:
    response = await member_client.get("/api/events", params={"when": "upcoming", "kind": "raid"})
    assert response.status_code == 200
    assert response.json() == []


async def test_signup_to_cancelled_event_is_409(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, status="cancelled")
    await login_as(member_client, discord_state, discord_id=2020, roles=[])
    response = await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body())
    assert response.status_code == 409


async def test_role_kind_signup_without_character_class_role_is_400(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="raid")
    await login_as(member_client, discord_state, discord_id=2021, roles=[])
    response = await member_client.put(f"/api/events/{event_id}/signup", json={"status": "signed"})
    assert response.status_code == 400


async def test_dungeon_kind_signup_without_character_class_role_is_400(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="dungeon")
    await login_as(member_client, discord_state, discord_id=2022, roles=[])
    response = await member_client.put(f"/api/events/{event_id}/signup", json={"status": "signed"})
    assert response.status_code == 400


async def test_role_kind_absent_signup_without_character_class_role_succeeds(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="raid")
    await login_as(member_client, discord_state, discord_id=2024, roles=[])
    response = await member_client.put(f"/api/events/{event_id}/signup", json={"status": "absent"})
    assert response.status_code == 200
    assert response.json()["character"] is None
    assert response.json()["class"] is None
    assert response.json()["role"] is None


async def test_social_kind_accepts_bare_rsvp(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="social")
    await login_as(member_client, discord_state, discord_id=2023, roles=[])
    response = await member_client.put(f"/api/events/{event_id}/signup", json={"status": "signed"})
    assert response.status_code == 200
    assert response.json()["character"] is None
    assert response.json()["class"] is None
    assert response.json()["role"] is None


async def test_officer_can_create_and_manage_event(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=2030, roles=[OFFICER_ROLE_ID])
    create_response = await member_client.post(
        "/api/events",
        json={
            "kind": "raid",
            "title": "Blackwing Lair",
            "location": "Blackwing Lair",
            "starts_at": "2026-12-05T20:00:00Z",
            "size": 40,
            "notes": "Bring flasks",
        },
    )
    assert create_response.status_code == 201
    event_id = create_response.json()["id"]

    update_response = await member_client.patch(f"/api/events/{event_id}", json={"status": "cancelled"})
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "cancelled"

    delete_response = await member_client.delete(f"/api/events/{event_id}")
    assert delete_response.status_code == 204


async def test_event_ep_follows_kind_preset_until_an_officer_overrides_it(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=2031, roles=[OFFICER_ROLE_ID])
    created = await member_client.post(
        "/api/events",
        json={"kind": "social", "title": "Movie Night", "starts_at": "2026-12-05T20:00:00Z"},
    )
    assert created.status_code == 201
    assert (created.json()["ep"], created.json()["ep_override"]) == (2, None)
    event_id = created.json()["id"]

    async def patch(body: dict) -> dict:
        response = await member_client.patch(f"/api/events/{event_id}", json=body)
        assert response.status_code == 200
        return response.json()

    assert (await patch({"kind": "dungeon"}))["ep"] == 5
    assert (await patch({"ep_override": 7}))["ep"] == 7
    assert (await patch({"kind": "transmog"}))["ep"] == 7
    assert (await patch({"ep_override": 0}))["ep"] == 0
    reverted = await patch({"ep_override": None})
    assert (reverted["ep"], reverted["ep_override"]) == (2, None)

    too_much = await member_client.patch(f"/api/events/{event_id}", json={"ep_override": 51})
    assert too_much.status_code == 400
    negative = await member_client.post(
        "/api/events",
        json={"kind": "social", "title": "Movie Night", "starts_at": "2026-12-05T20:00:00Z", "ep_override": -1},
    )
    assert negative.status_code == 400


async def test_officer_raid_chart_places_signup_in_group(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="raid")
    await login_as(member_client, discord_state, discord_id=2040, roles=[])
    signup = await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body())
    signup_id = signup.json()["id"]

    await login_as(member_client, discord_state, discord_id=2041, roles=[OFFICER_ROLE_ID])
    chart_response = await member_client.patch(
        f"/api/events/{event_id}/signups/{signup_id}", json={"group": 3, "bench": False}
    )
    assert chart_response.status_code == 200
    assert chart_response.json()["group"] == 3
    assert chart_response.json()["bench"] is False


async def test_officer_raid_chart_on_non_raid_event_is_409(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, kind="dungeon")
    await login_as(member_client, discord_state, discord_id=2042, roles=[])
    signup = await member_client.put(
        f"/api/events/{event_id}/signup", json=_signup_body(character="Thrall", role="dps")
    )
    signup_id = signup.json()["id"]

    await login_as(member_client, discord_state, discord_id=2043, roles=[OFFICER_ROLE_ID])
    chart_response = await member_client.patch(
        f"/api/events/{event_id}/signups/{signup_id}", json={"group": 3, "bench": False}
    )
    assert chart_response.status_code == 409


async def test_create_event_rejects_ends_at_before_starts_at(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=2050, roles=[OFFICER_ROLE_ID])
    response = await member_client.post(
        "/api/events",
        json={
            "kind": "raid",
            "title": "Blackwing Lair",
            "location": "Blackwing Lair",
            "starts_at": "2026-12-05T20:00:00Z",
            "ends_at": "2026-12-05T19:00:00Z",
            "size": 40,
            "notes": None,
        },
    )
    assert response.status_code == 400


async def test_update_event_rejects_ends_at_not_after_stored_starts_at(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    starts_at = datetime.now(UTC) + timedelta(days=1)
    event_id = await _seed_event(db_sessionmaker, starts_at=starts_at)
    await login_as(member_client, discord_state, discord_id=2051, roles=[OFFICER_ROLE_ID])
    response = await member_client.patch(
        f"/api/events/{event_id}", json={"ends_at": (starts_at - timedelta(hours=1)).isoformat()}
    )
    assert response.status_code == 400


async def test_update_event_rejects_new_starts_at_after_stored_ends_at(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    starts_at = datetime.now(UTC) + timedelta(days=1)
    event_id = await _seed_event(db_sessionmaker, starts_at=starts_at)
    async with db_sessionmaker() as session:
        event = await session.get(GuildEvent, UUID(event_id))
        assert event is not None
        event.ends_at = starts_at + timedelta(hours=3)
        await session.commit()
    await login_as(member_client, discord_state, discord_id=2052, roles=[OFFICER_ROLE_ID])
    response = await member_client.patch(
        f"/api/events/{event_id}", json={"starts_at": (starts_at + timedelta(hours=4)).isoformat()}
    )
    assert response.status_code == 400


async def _activity_rows(db_sessionmaker: async_sessionmaker[AsyncSession], event_id: str) -> list[EventSignupActivity]:
    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(EventSignupActivity).where(EventSignupActivity.event_id == UUID(event_id))))
            .scalars()
            .all()
        )
        return sorted(rows, key=lambda row: row.created_at)


async def test_new_signup_writes_going_activity(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=3001, roles=[])
    body = _signup_body(status="signed")
    body["comment"] = "Can we play Hello Kitty Island Adventure instead, please"
    response = await member_client.put(f"/api/events/{event_id}/signup", json=body)
    assert response.status_code == 200
    rows = await _activity_rows(db_sessionmaker, event_id)
    assert len(rows) == 1
    assert rows[0].action == "going"
    assert rows[0].detail == "Thrall · Warrior · DPS"
    assert rows[0].discord_id == 3001
    assert rows[0].comment == "Can we play Hello Kitty Island Adventure instead, please"


async def test_status_change_writes_new_activity_row(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=3002, roles=[])
    await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body(status="signed"))
    await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body(status="tentative"))
    rows = await _activity_rows(db_sessionmaker, event_id)
    assert [row.action for row in rows] == ["going", "maybe"]


async def test_only_a_new_non_empty_comment_writes_activity_when_status_is_unchanged(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=3003, roles=[])
    body = _signup_body(status="signed")
    await member_client.put(f"/api/events/{event_id}/signup", json=body)
    body["comment"] = "bring flasks"
    await member_client.put(f"/api/events/{event_id}/signup", json=body)  # new comment: posts
    body["character"] = "Jaina"
    await member_client.put(f"/api/events/{event_id}/signup", json=body)  # same comment: silent
    body["comment"] = None
    await member_client.put(f"/api/events/{event_id}/signup", json=body)  # cleared: silent
    rows = await _activity_rows(db_sessionmaker, event_id)
    assert [(row.action, row.comment) for row in rows] == [("going", None), ("going", "bring flasks")]


async def test_withdraw_writes_withdrew_activity(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=3004, roles=[])
    await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body(status="signed"))
    response = await member_client.delete(f"/api/events/{event_id}/signup")
    assert response.status_code == 204
    rows = await _activity_rows(db_sessionmaker, event_id)
    assert [row.action for row in rows] == ["going", "withdrew"]
    assert rows[-1].detail is None


async def test_discord_interest_counts_everyone_but_names_only_site_members(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=4001, username="coffee", roles=[])
    async with db_sessionmaker() as session:
        session.add_all(
            [
                EventDiscordInterest(event_id=UUID(event_id), discord_id=4001),
                EventDiscordInterest(event_id=UUID(event_id), discord_id=9999999),
            ]
        )
        await session.commit()
    detail = await member_client.get(f"/api/events/{event_id}")
    discord_interest = detail.json()["discord_interest"]
    assert discord_interest["count"] == 2
    assert [m["display_name"] for m in discord_interest["members"]] == ["coffee"]


async def test_event_summary_counts_include_interested(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    async with db_sessionmaker() as session:
        session.add(EventDiscordInterest(event_id=UUID(event_id), discord_id=5001))
        await session.commit()
    await login_as(member_client, discord_state, discord_id=5002)
    response = await member_client.get("/api/events", params={"when": "upcoming"})
    summary = next(event for event in response.json() if event["id"] == event_id)
    assert summary["counts"]["interested"] == 1


async def test_anonymous_list_hides_counts_but_keeps_headline_fields(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker, title="Molten Core")
    response = await member_client.get("/api/events", params={"when": "upcoming"})
    assert response.status_code == 200
    summary = next(event for event in response.json() if event["id"] == event_id)
    assert summary["title"] == "Molten Core"
    assert summary["kind"] == "raid"
    assert summary["location"] == "Molten Core"
    assert summary["counts"] is None


async def test_anonymous_detail_hides_signups_counts_notes_and_interest(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=6001, username="watcher", roles=[])
    await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body(character="Watcher"))
    async with db_sessionmaker() as session:
        session.add(EventDiscordInterest(event_id=UUID(event_id), discord_id=6001))
        await session.commit()
    await member_client.post("/auth/logout")

    response = await member_client.get(f"/api/events/{event_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Molten Core"
    assert body["signups"] == []
    assert body["my_signup"] is None
    assert body["notes"] is None
    assert body["counts"] is None
    assert body["discord_interest"] is None


async def test_bot_api_key_gets_full_list_and_detail(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=6101, username="raider", roles=[])
    await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body(character="Raider"))
    await member_client.post("/auth/logout")

    headers = {API_KEY_HEADER: TEST_API_KEY}
    list_response = await member_client.get("/api/events", params={"when": "upcoming"}, headers=headers)
    summary = next(event for event in list_response.json() if event["id"] == event_id)
    assert summary["counts"]["signed"] == 1

    detail_response = await member_client.get(f"/api/events/{event_id}", headers=headers)
    body = detail_response.json()
    assert body["counts"]["signed"] == 1
    assert [s["character"] for s in body["signups"]] == ["Raider"]
    assert body["discord_interest"] is not None


async def test_signed_in_guest_sees_full_roster(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=6201, username="confirmed", roles=[])
    await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body(character="Confirmed"))

    await login_as(member_client, discord_state, discord_id=6202, username="guest", is_guild_member=False)
    response = await member_client.get(f"/api/events/{event_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"] is not None
    assert [s["character"] for s in body["signups"]] == ["Confirmed"]
