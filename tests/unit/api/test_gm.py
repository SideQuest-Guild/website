"""HTTP-level tests for the GM console (``/api/gm/*``), guild role names, and the officer audit trail.

See ``local://gm-console-contract.md``.
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select

from sidequest_common.models import (
    EventSignupActivity,
    GuildEvent,
    GuildRole,
    Member,
    MemberLevel,
    ModCase,
    OfficerAudit,
)
from tests.conftest import GUILD_ID
from tests.unit.api.conftest import GM_ROLE_ID, OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SERIES_BODY = {
    "kind": "raid",
    "title": "Molten Core",
    "location": "Molten Core",
    "size": 40,
    "notes": None,
    "weekdays": [4],
    "interval_weeks": 1,
    "start_time": "19:00",
    "timezone": "America/Chicago",
    "duration_minutes": 180,
    "starts_on": "2026-01-02",
}


def _signup_body(
    character: str = "Thrall", role: str = "dps", wow_class: str = "warrior", status: str = "signed"
) -> dict:
    return {"character": character, "class": wow_class, "role": role, "status": status, "comment": None}


async def _seed_event(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    title: str = "Molten Core",
    starts_at: datetime | None = None,
) -> GuildEvent:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind="raid",
            title=title,
            location="Molten Core",
            starts_at=starts_at or (datetime.now(UTC) + timedelta(days=1)),
            size=40,
            status="scheduled",
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event


async def _seed_member(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    discord_id: int,
    username: str,
    is_guild_member: bool = True,
    roles: list[int] | None = None,
    created_at: datetime | None = None,
) -> Member:
    async with db_sessionmaker() as session:
        member = Member(
            discord_id=discord_id,
            username=username,
            is_guild_member=is_guild_member,
            roles=roles or [],
            created_at=created_at or datetime.now(UTC),
        )
        session.add(member)
        await session.commit()
        await session.refresh(member)
        return member


async def _seed_case(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user_id: int = 12345,
    moderator_id: int = 777,
    case_number: int = 1,
    reason: str = "initial reason",
    created_at: datetime | None = None,
) -> None:
    async with db_sessionmaker() as session:
        session.add(
            ModCase(
                guild_id=GUILD_ID,
                case_number=case_number,
                action="warn",
                user_id=user_id,
                moderator_id=moderator_id,
                reason=reason,
                created_at=created_at or datetime.now(UTC),
            )
        )
        await session.commit()


def _gm_requests(member_id: int, case_number: int) -> list[tuple[str, str, dict | None]]:
    return [
        ("GET", "/api/gm/members", None),
        ("GET", f"/api/gm/members/{member_id}", None),
        ("GET", "/api/gm/log", None),
        ("GET", "/api/gm/cases", None),
        ("PATCH", f"/api/gm/cases/{case_number}", {"reason": "updated reason"}),
    ]


async def _send(client: AsyncTestClient, method: str, path: str, body: dict | None) -> httpx.Response:
    if method == "GET":
        return await client.get(path)
    return await client.patch(path, json=body)


# --- GM guard ------------------------------------------------------------------------------------------------------


async def test_gm_routes_require_sign_in(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member = await _seed_member(db_sessionmaker, discord_id=6001, username="target")
    await _seed_case(db_sessionmaker, case_number=1)
    for method, path, body in _gm_requests(member.id, 1):
        response = await _send(member_client, method, path, body)
        assert response.status_code == 401, path


async def test_gm_routes_require_gm_role_not_just_officer(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member = await _seed_member(db_sessionmaker, discord_id=6002, username="target2")
    await _seed_case(db_sessionmaker, case_number=2)
    await login_as(member_client, discord_state, discord_id=6003, username="officer", roles=[OFFICER_ROLE_ID])
    for method, path, body in _gm_requests(member.id, 2):
        response = await _send(member_client, method, path, body)
        assert response.status_code == 403, path


async def test_gm_routes_allow_gm(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member = await _seed_member(db_sessionmaker, discord_id=6004, username="target3")
    await _seed_case(db_sessionmaker, case_number=3)
    await login_as(member_client, discord_state, discord_id=6005, username="gm", roles=[GM_ROLE_ID])
    for method, path, body in _gm_requests(member.id, 3):
        response = await _send(member_client, method, path, body)
        assert response.status_code == 200, path


# --- GET /api/gm/members --------------------------------------------------------------------------------------------


async def test_list_members_sorted_guild_members_first_then_casefold(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=6101, username="Zelda", is_guild_member=True)
    await login_as(member_client, discord_state, discord_id=6102, username="alice", is_guild_member=False)
    await login_as(member_client, discord_state, discord_id=6103, username="Bob", is_guild_member=True)
    await login_as(
        member_client, discord_state, discord_id=6104, username="gm", roles=[GM_ROLE_ID], is_guild_member=True
    )

    response = await member_client.get("/api/gm/members")
    assert response.status_code == 200
    names = [m["display_name"] for m in response.json()]
    assert names == ["Bob", "gm", "Zelda", "alice"]


async def test_list_members_resolves_roles_highest_position_first_drops_managed_and_unknown(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        session.add_all(
            [
                GuildRole(guild_id=GUILD_ID, role_id=10, name="Raider", color=0xFF0000, position=1, managed=False),
                GuildRole(guild_id=GUILD_ID, role_id=20, name="Officer", color=0, position=5, managed=False),
                GuildRole(guild_id=GUILD_ID, role_id=30, name="Bot", color=0x00FF00, position=10, managed=True),
            ]
        )
        await session.commit()

    await login_as(member_client, discord_state, discord_id=6201, username="tagged", roles=[10, 20, 30, 999999])
    await login_as(member_client, discord_state, discord_id=6202, username="gm", roles=[GM_ROLE_ID])

    response = await member_client.get("/api/gm/members")
    assert response.status_code == 200
    member = next(m for m in response.json() if m["display_name"] == "tagged")
    assert [role["id"] for role in member["roles"]] == ["20", "10"]
    assert member["roles"][0]["color"] is None
    assert member["roles"][1]["color"] == "#ff0000"


async def test_list_members_includes_signup_case_and_level_aggregates(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event = await _seed_event(db_sessionmaker, title="Blackwing Lair")
    await login_as(member_client, discord_state, discord_id=6301, username="grinder")
    await member_client.put(f"/api/events/{event.id}/signup", json=_signup_body())
    member_id = (await member_client.get("/api/me")).json()["id"]

    async with db_sessionmaker() as session:
        session.add_all(
            [
                ModCase(guild_id=GUILD_ID, case_number=1, action="warn", user_id=6301, moderator_id=777, reason="x"),
                ModCase(guild_id=GUILD_ID, case_number=2, action="warn", user_id=6301, moderator_id=777, reason="y"),
                MemberLevel(guild_id=GUILD_ID, user_id=6301, level=12, xp=5000, message_count=300),
            ]
        )
        await session.commit()

    await login_as(member_client, discord_state, discord_id=6999, username="gm", roles=[GM_ROLE_ID])
    response = await member_client.get("/api/gm/members")
    member = next(m for m in response.json() if m["id"] == member_id)
    assert member["signup_count"] == 1
    assert member["case_count"] == 2
    assert member["level"] == 12


# --- GET /api/gm/members/{id} ---------------------------------------------------------------------------------------


async def test_member_detail_unknown_is_404(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=7300, username="gm", roles=[GM_ROLE_ID])
    response = await member_client.get("/api/gm/members/999999")
    assert response.status_code == 404


async def test_member_detail_signups_newest_first_and_cases_newest_first_with_resolved_names(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    older_event = await _seed_event(
        db_sessionmaker, title="Molten Core", starts_at=datetime.now(UTC) + timedelta(days=1)
    )
    newer_event = await _seed_event(
        db_sessionmaker, title="Blackwing Lair", starts_at=datetime.now(UTC) + timedelta(days=5)
    )

    await login_as(member_client, discord_state, discord_id=7301, username="target", roles=[])
    member_id = (await member_client.get("/api/me")).json()["id"]
    await member_client.put(
        f"/api/events/{older_event.id}/signup", json=_signup_body(character="A", role="tank", status="signed")
    )
    await member_client.put(
        f"/api/events/{newer_event.id}/signup",
        json=_signup_body(character="B", role="dps", wow_class="mage", status="tentative"),
    )

    async with db_sessionmaker() as session:
        session.add_all(
            [
                ModCase(
                    guild_id=GUILD_ID, case_number=1, action="warn", user_id=7301, moderator_id=7301, reason="first"
                ),
                ModCase(
                    guild_id=GUILD_ID, case_number=2, action="timeout", user_id=7301, moderator_id=7301, reason="second"
                ),
            ]
        )
        await session.commit()

    await login_as(member_client, discord_state, discord_id=7302, username="gm", roles=[GM_ROLE_ID])
    response = await member_client.get(f"/api/gm/members/{member_id}")
    assert response.status_code == 200
    body = response.json()
    assert [s["title"] for s in body["signups"]] == ["Blackwing Lair", "Molten Core"]
    assert [s["status"] for s in body["signups"]] == ["tentative", "signed"]
    assert [c["case_number"] for c in body["cases"]] == [2, 1]
    assert body["cases"][0]["user_name"] == "target"
    assert body["cases"][0]["moderator_name"] == "target"


# --- GET /api/gm/log -------------------------------------------------------------------------------------------------


async def test_log_merges_all_kinds_newest_first_filters_by_kind_before_is_strict_and_pages(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    base = datetime.now(UTC)

    await login_as(member_client, discord_state, discord_id=7100, username="gm", roles=[GM_ROLE_ID])
    gm_id = (await member_client.get("/api/me")).json()["id"]
    async with db_sessionmaker() as session:
        gm_member = await session.get(Member, gm_id)
        assert gm_member is not None
        gm_member.created_at = base - timedelta(days=30)
        await session.commit()

    event = await _seed_event(db_sessionmaker, title="Icecrown Citadel")
    async with db_sessionmaker() as session:
        member_sign_in = Member(discord_id=7101, username="Newbie", created_at=base - timedelta(seconds=60))
        member_bnet = Member(
            discord_id=7102,
            username="Linker",
            created_at=base - timedelta(days=10),
            battlenet_linked_at=base - timedelta(seconds=120),
        )
        member_officer_actor = Member(discord_id=7103, username="Captain", created_at=base - timedelta(days=10))
        session.add_all([member_sign_in, member_bnet, member_officer_actor])
        await session.flush()

        session.add(
            EventSignupActivity(
                event_id=event.id,
                display_name="Rogue",
                action="going",
                discord_id=7104,
                created_at=base,
            )
        )
        session.add(
            OfficerAudit(
                actor_member_id=member_officer_actor.id,
                actor_name=member_officer_actor.display_name,
                action="case.edit",
                subject_type="case",
                subject_id="1",
                summary="Edited the reason on case #1",
                created_at=base - timedelta(seconds=180),
            )
        )
        session.add(
            ModCase(
                guild_id=GUILD_ID,
                case_number=99,
                action="warn",
                user_id=8888,
                moderator_id=9999,
                reason="spam",
                created_at=base - timedelta(seconds=240),
            )
        )
        await session.commit()

    # Merge: newest first across all five kinds.
    response = await member_client.get("/api/gm/log")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [e["kind"] for e in entries[:5]] == ["signup", "sign_in", "battlenet", "officer", "moderation"]
    assert entries[3]["actor"]["display_name"] == "Captain"

    # Kind filter is repeatable.
    filtered = await member_client.get("/api/gm/log", params=[("kind", "officer"), ("kind", "moderation")])
    assert filtered.status_code == 200
    assert {e["kind"] for e in filtered.json()["entries"]} == {"officer", "moderation"}

    # before is strict (< before, not <=): the battlenet entry sits exactly at `before` and must be excluded.
    strict = await member_client.get(
        "/api/gm/log", params=[("kind", "battlenet"), ("before", (base - timedelta(seconds=120)).isoformat())]
    )
    assert strict.status_code == 200
    assert strict.json()["entries"] == []

    # limit + next_before: a full page returns the last entry's `at`; a short page returns null.
    paged = await member_client.get("/api/gm/log", params={"limit": 2})
    assert paged.status_code == 200
    page_body = paged.json()
    assert len(page_body["entries"]) == 2
    assert page_body["next_before"] == page_body["entries"][-1]["at"]

    short_page = await member_client.get("/api/gm/log", params=[("kind", "moderation"), ("limit", 50)])
    assert short_page.status_code == 200
    short_body = short_page.json()
    assert len(short_body["entries"]) < 50
    assert short_body["next_before"] is None


# --- PATCH /api/gm/cases/{n} -----------------------------------------------------------------------------------------


async def test_update_case_reason_validates_updates_and_audits(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_case(db_sessionmaker, user_id=5555, moderator_id=6666, case_number=42)
    await login_as(member_client, discord_state, discord_id=7200, username="gm", roles=[GM_ROLE_ID])

    too_long = await member_client.patch("/api/gm/cases/42", json={"reason": "x" * 501})
    assert too_long.status_code == 400

    empty = await member_client.patch("/api/gm/cases/42", json={"reason": ""})
    assert empty.status_code == 400

    missing = await member_client.patch("/api/gm/cases/999999", json={"reason": "valid reason"})
    assert missing.status_code == 404

    response = await member_client.patch("/api/gm/cases/42", json={"reason": "corrected reason"})
    assert response.status_code == 200
    assert response.json()["reason"] == "corrected reason"

    async with db_sessionmaker() as session:
        audits = (await session.execute(select(OfficerAudit).where(OfficerAudit.action == "case.edit"))).scalars().all()
        assert len(audits) == 1
        assert audits[0].subject_id == "42"
        assert audits[0].actor_name == "gm"


# --- Officer audit trail ----------------------------------------------------------------------------------------------


async def test_officer_action_families_write_audit_rows_with_actor_name(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=7400, username="Captain Officer", roles=[OFFICER_ROLE_ID])

    event_response = await member_client.post(
        "/api/events",
        json={
            "kind": "raid",
            "title": "Onyxia's Lair",
            "location": "Onyxia's Lair",
            "starts_at": "2026-12-05T20:00:00Z",
            "size": 40,
            "notes": None,
        },
    )
    assert event_response.status_code == 201

    series_response = await member_client.post("/api/event-series", json=_SERIES_BODY)
    assert series_response.status_code == 201

    addon_response = await member_client.post(
        "/api/addons",
        json={
            "slug": "deadly-boss-mods",
            "name": "Deadly Boss Mods",
            "summary": "Raid warnings",
            "version": "1.0.0",
            "download_url": "https://example.com/dbm.zip",
            "homepage_url": None,
        },
    )
    assert addon_response.status_code == 201

    await login_as(member_client, discord_state, discord_id=7401, username="target", roles=[])
    target_id = (await member_client.get("/api/me")).json()["id"]

    await login_as(member_client, discord_state, discord_id=7402, username="GM Leader", roles=[GM_ROLE_ID])
    confirm_response = await member_client.put(f"/api/members/{target_id}/roster-confirmation")
    assert confirm_response.status_code == 200

    async with db_sessionmaker() as session:
        audits = (await session.execute(select(OfficerAudit))).scalars().all()
        by_action = {audit.action: audit for audit in audits}
        assert by_action["event.create"].actor_name == "Captain Officer"
        assert by_action["series.create"].actor_name == "Captain Officer"
        assert by_action["addon.create"].actor_name == "Captain Officer"
        assert by_action["roster.confirm"].actor_name == "GM Leader"


async def test_roster_confirmation_is_403_for_non_gm_officer(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=7403, username="target2", roles=[])
    target_id = (await member_client.get("/api/me")).json()["id"]

    await login_as(member_client, discord_state, discord_id=7404, username="officer-only", roles=[OFFICER_ROLE_ID])
    response = await member_client.put(f"/api/members/{target_id}/roster-confirmation")
    assert response.status_code == 403


# --- PUT /api/guilds/{guild_id}/roles --------------------------------------------------------------------------------


async def test_replace_guild_roles_is_full_replace_and_404s_for_other_guilds(
    client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    body = {
        "roles": [
            {"id": 10, "name": "Raider", "color": 0xFF0000, "position": 1, "managed": False},
            {"id": 20, "name": "Bot", "color": 0, "position": 2, "managed": True},
        ]
    }
    wrong_guild = await client.put(f"/api/guilds/{GUILD_ID + 1}/roles/", json=body)
    assert wrong_guild.status_code == 404

    first = await client.put(f"/api/guilds/{GUILD_ID}/roles/", json=body)
    assert first.status_code == 204

    replacement = {"roles": [{"id": 30, "name": "Scout", "color": 0x00FF00, "position": 3, "managed": False}]}
    second = await client.put(f"/api/guilds/{GUILD_ID}/roles/", json=replacement)
    assert second.status_code == 204

    async with db_sessionmaker() as session:
        rows = (await session.execute(select(GuildRole).where(GuildRole.guild_id == GUILD_ID))).scalars().all()
        assert [row.role_id for row in rows] == [30]
        assert rows[0].name == "Scout"
