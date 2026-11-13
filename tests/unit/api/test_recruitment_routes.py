"""Recruitment drive routes: member drive detail, officer payouts list/mark-paid, and SQI1 game-import additions."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import GuildEvent, Member, RecruitmentRecruit
from sidequest_common.schemas import DRIVE_PRIZE_COPPER, DRIVE_SETTLE_DAYS
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime.now(UTC)


async def _login_officer(client: AsyncTestClient, discord_state: dict, *, discord_id: int = 7700) -> None:
    response = await login_as(client, discord_state, discord_id=discord_id, roles=[OFFICER_ROLE_ID])
    assert response.status_code == 302, response.text


async def _create_member_sync_token(
    client: AsyncTestClient, discord_state: dict, *, discord_id: int, name: str = "Companion"
) -> str:
    """Any guild member's device-sign-in flow (no officer role needed): create, self-approve, and poll for the
    token, same as SideQuest Companion does."""
    created = await client.post("/api/epgp/device-authorizations", json={"device_name": name})
    assert created.status_code == 201, created.text
    await login_as(client, discord_state, discord_id=discord_id, roles=[])
    approve = await client.post(f"/api/epgp/device-authorizations/{created.json()['user_code']}/approve")
    assert approve.status_code == 204, approve.text
    poll = await client.post(
        "/api/epgp/device-authorizations/token", json={"device_code": created.json()["device_code"]}
    )
    assert poll.status_code == 200, poll.text
    assert poll.json()["status"] == "approved", poll.text
    return poll.json()["token"]


async def _seed_drive(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    title: str = "Autumn Recruitment Drive",
    starts_at: datetime,
    ends_at: datetime,
    status: str = "scheduled",
) -> str:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind="recruitment",
            title=title,
            location="",
            starts_at=starts_at,
            ends_at=ends_at,
            status=status,
            notes=None,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return str(event.id)


async def _seed_recruit(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    event_id: str,
    recruit_name: str = "Newbie",
    inviter_name: str = "Thrall",
    status: str = "qualified",
    invited_at: datetime | None = None,
    joined_at: datetime | None = None,
    qualifies_at: datetime | None = None,
    qualified_at: datetime | None = None,
    paid_at: datetime | None = None,
    paid_by: str | None = None,
    paid_via: str | None = None,
) -> str:
    async with db_sessionmaker() as session:
        row = RecruitmentRecruit(
            event_id=event_id,
            recruit_name=recruit_name,
            inviter_name=inviter_name,
            invited_at=invited_at or (NOW - timedelta(days=20)),
            status=status,
            joined_at=joined_at,
            qualifies_at=qualifies_at,
            qualified_at=qualified_at,
            paid_at=paid_at,
            paid_by=paid_by,
            paid_via=paid_via,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return str(row.id)


# --- POST /api/events (kind recruitment) ---------------------------------------------------------------------


async def test_officer_creates_a_drive_only_with_an_end_and_a_future_start(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await _login_officer(member_client, discord_state, discord_id=7790)
    body = {
        "kind": "recruitment",
        "title": "Winter Recruitment Drive",
        "location": "",
        "starts_at": (NOW + timedelta(hours=1)).isoformat(),
        "size": None,
        "notes": None,
    }
    assert (await member_client.post("/api/events", json=body)).status_code == 400  # no ends_at
    body["ends_at"] = (NOW + timedelta(days=14)).isoformat()
    started = {**body, "starts_at": (NOW - timedelta(minutes=5)).isoformat()}
    assert (await member_client.post("/api/events", json=started)).status_code == 400  # Discord can't post it
    created = await member_client.post("/api/events", json=body)
    assert created.status_code == 201, created.text
    assert created.json()["kind"] == "recruitment"


# --- GET /api/events/{event_id}/recruitment ------------------------------------------------------------------


async def test_member_can_read_a_drive(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=1), ends_at=NOW + timedelta(days=13))
    await login_as(member_client, discord_state, discord_id=7701, roles=[])
    response = await member_client.get(f"/api/events/{event_id}/recruitment")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event_id"] == event_id
    assert body["reward_copper"] == DRIVE_PRIZE_COPPER
    assert body["totals"] == {"invited": 0, "joined": 0, "counting": 0, "qualified": 0, "disqualified": 0, "paid": 0}
    assert body["leaders"] == []
    assert body["recruits"] == []


async def test_member_sync_token_can_read_a_drive(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=1), ends_at=NOW + timedelta(days=13))
    token = await _create_member_sync_token(member_client, discord_state, discord_id=7706)
    await member_client.post("/auth/logout")
    response = await member_client.get(
        f"/api/events/{event_id}/recruitment", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["event_id"] == event_id


async def test_non_member_sync_token_cannot_read_a_drive(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=1), ends_at=NOW + timedelta(days=13))
    token = await _create_member_sync_token(member_client, discord_state, discord_id=7707)
    async with db_sessionmaker() as session:
        member = (await session.execute(select(Member).where(Member.discord_id == 7707))).scalar_one()
        member.is_guild_member = False
        await session.commit()
    response = await member_client.get(
        f"/api/events/{event_id}/recruitment", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


async def test_signed_out_visitor_cannot_read_a_drive(
    member_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=1), ends_at=NOW + timedelta(days=13))
    response = await member_client.get(f"/api/events/{event_id}/recruitment")
    assert response.status_code == 401


async def test_non_member_cannot_read_a_drive(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=1), ends_at=NOW + timedelta(days=13))
    await login_as(member_client, discord_state, discord_id=7702, is_guild_member=False, roles=[])
    response = await member_client.get(f"/api/events/{event_id}/recruitment")
    assert response.status_code == 403


async def test_non_drive_event_is_404(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind="raid", title="Molten Core", location="", starts_at=NOW - timedelta(hours=2), status="scheduled"
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        event_id = str(event.id)
    await login_as(member_client, discord_state, discord_id=7703, roles=[])
    response = await member_client.get(f"/api/events/{event_id}/recruitment")
    assert response.status_code == 404


# --- GET /api/recruitment/payouts, POST /api/recruitment/payouts/paid ----------------------------------------


async def test_payouts_list_is_officer_only(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=30), ends_at=NOW - timedelta(days=16))
    await login_as(member_client, discord_state, discord_id=7704, roles=[])
    response = await member_client.get("/api/recruitment/payouts")
    assert response.status_code == 403


async def test_mark_paid_is_officer_only(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=30), ends_at=NOW - timedelta(days=16))
    await login_as(member_client, discord_state, discord_id=7705, roles=[])
    response = await member_client.post(
        "/api/recruitment/payouts/paid", json={"event_id": event_id, "inviter": "Thrall"}
    )
    assert response.status_code == 403


async def test_officer_lists_and_marks_a_payout_paid(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    # Settled 16+ days ago (ends_at + DRIVE_SETTLE_DAYS is well in the past).
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=30), ends_at=NOW - timedelta(days=16))
    await _seed_recruit(db_sessionmaker, event_id=event_id, recruit_name="Newbie", inviter_name="Thrall")
    await _login_officer(member_client, discord_state, discord_id=7706)

    listed = await member_client.get("/api/recruitment/payouts")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    row = next(r for r in rows if r["event_id"] == event_id and r["inviter"] == "Thrall")
    assert row["copper"] == DRIVE_PRIZE_COPPER
    assert row["recruits"] == ["Newbie"]
    assert row["paid_at"] is None

    marked = await member_client.post("/api/recruitment/payouts/paid", json={"event_id": event_id, "inviter": "Thrall"})
    assert marked.status_code == 204, marked.text

    recruit_id = await _recruit_id(db_sessionmaker, event_id, "Newbie")
    async with db_sessionmaker() as session:
        refreshed = await session.get(RecruitmentRecruit, recruit_id)
        assert refreshed is not None
        assert refreshed.paid_at is not None
        assert refreshed.paid_via == "site"
        assert refreshed.paid_by == "tester"

    relisted = await member_client.get("/api/recruitment/payouts")
    paid_row = next(r for r in relisted.json() if r["event_id"] == event_id and r["inviter"] == "Thrall")
    assert paid_row["paid_at"] is not None
    assert paid_row["paid_via"] == "site"


async def test_mark_paid_is_idempotent(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=30), ends_at=NOW - timedelta(days=16))
    await _seed_recruit(db_sessionmaker, event_id=event_id, recruit_name="Newbie", inviter_name="Thrall")
    await _login_officer(member_client, discord_state, discord_id=7707)

    first = await member_client.post("/api/recruitment/payouts/paid", json={"event_id": event_id, "inviter": "Thrall"})
    assert first.status_code == 204, first.text
    recruit_id = await _recruit_id(db_sessionmaker, event_id, "Newbie")
    async with db_sessionmaker() as session:
        row = await session.get(RecruitmentRecruit, recruit_id)
        assert row is not None
        paid_at_first = row.paid_at
    assert paid_at_first is not None

    second = await member_client.post("/api/recruitment/payouts/paid", json={"event_id": event_id, "inviter": "Thrall"})
    assert second.status_code == 204, second.text
    async with db_sessionmaker() as session:
        row = await session.get(RecruitmentRecruit, recruit_id)
        assert row is not None
        assert row.paid_at == paid_at_first  # unchanged: the second call found no unpaid qualified rows


async def _recruit_id(db_sessionmaker: async_sessionmaker[AsyncSession], event_id: str, recruit_name: str) -> str:
    async with db_sessionmaker() as session:
        row = (
            await session.execute(
                select(RecruitmentRecruit).where(
                    RecruitmentRecruit.event_id == event_id, RecruitmentRecruit.recruit_name == recruit_name
                )
            )
        ).scalar_one()
        return str(row.id)


# --- SQI1 game-import additions -------------------------------------------------------------------------------


async def test_sqi1_includes_a_running_drive_with_ends_at(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A drive that started well outside the normal upcoming window but hasn't ended yet still shows up."""
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=10), ends_at=NOW + timedelta(days=4))
    await _login_officer(member_client, discord_state, discord_id=7708)
    response = await member_client.get("/api/epgp/game-import")
    assert response.status_code == 200, response.text
    decoded = json.loads(base64.b64decode(response.json()["payload"][len("SQI1:") :]))
    events_by_id = {e["id"]: e for e in decoded["events"]}
    assert event_id in events_by_id
    drive = events_by_id[event_id]
    assert drive["kind"] == "recruitment"
    assert drive["ends_at"] is not None


async def test_sqi1_recruit_payouts_only_settled_and_unpaid(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    # Settled drive with one unpaid qualified recruit: must appear.
    settled_unpaid = await _seed_drive(
        db_sessionmaker,
        title="Settled unpaid drive",
        starts_at=NOW - timedelta(days=30),
        ends_at=NOW - timedelta(days=16),
    )
    await _seed_recruit(db_sessionmaker, event_id=settled_unpaid, recruit_name="Unpaid", inviter_name="Jaina")

    # Settled drive, but the recruit is already paid: must not appear.
    settled_paid = await _seed_drive(
        db_sessionmaker,
        title="Settled paid drive",
        starts_at=NOW - timedelta(days=30),
        ends_at=NOW - timedelta(days=16),
    )
    await _seed_recruit(
        db_sessionmaker,
        event_id=settled_paid,
        recruit_name="Paid",
        inviter_name="Anduin",
        paid_at=NOW - timedelta(days=1),
        paid_by="Officername",
        paid_via="site",
    )

    # Not yet settled (ends_at + DRIVE_SETTLE_DAYS is still in the future): must not appear.
    not_settled = await _seed_drive(
        db_sessionmaker, title="Fresh drive", starts_at=NOW - timedelta(days=2), ends_at=NOW - timedelta(hours=1)
    )
    await _seed_recruit(db_sessionmaker, event_id=not_settled, recruit_name="TooSoon", inviter_name="Sylvanas")

    await _login_officer(member_client, discord_state, discord_id=7709)
    response = await member_client.get("/api/epgp/game-import")
    assert response.status_code == 200, response.text
    decoded = json.loads(base64.b64decode(response.json()["payload"][len("SQI1:") :]))
    payouts = decoded["officer"]["recruit_payouts"]
    payouts_by_event = {p["event_id"]: p for p in payouts}

    assert settled_unpaid in payouts_by_event
    unpaid_payout = payouts_by_event[settled_unpaid]
    assert unpaid_payout["inviter"] == "Jaina"
    assert unpaid_payout["recruits"] == ["Unpaid"]
    assert unpaid_payout["copper"] == DRIVE_PRIZE_COPPER

    assert settled_paid not in payouts_by_event
    assert not_settled not in payouts_by_event

    assert DRIVE_SETTLE_DAYS == 7  # sanity: the fixture's "not yet settled" window assumes a 7-day settle delay


async def test_sqi1_recruit_payouts_lists_winners_only(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Within one settled drive, only the inviter(s) tied for the most qualifying recruits appear."""
    event_id = await _seed_drive(
        db_sessionmaker, title="Tied drive", starts_at=NOW - timedelta(days=30), ends_at=NOW - timedelta(days=16)
    )
    await _seed_recruit(db_sessionmaker, event_id=event_id, recruit_name="WinnerRecruitOne", inviter_name="Jaina")
    await _seed_recruit(db_sessionmaker, event_id=event_id, recruit_name="WinnerRecruitTwo", inviter_name="Jaina")
    await _seed_recruit(db_sessionmaker, event_id=event_id, recruit_name="LoserRecruit", inviter_name="Anduin")

    await _login_officer(member_client, discord_state, discord_id=7710)
    response = await member_client.get("/api/epgp/game-import")
    assert response.status_code == 200, response.text
    decoded = json.loads(base64.b64decode(response.json()["payload"][len("SQI1:") :]))
    payouts = decoded["officer"]["recruit_payouts"]
    drive_payouts = [p for p in payouts if p["event_id"] == event_id]
    assert [p["inviter"] for p in drive_payouts] == ["Jaina"]
    assert sorted(drive_payouts[0]["recruits"]) == ["WinnerRecruitOne", "WinnerRecruitTwo"]
    assert drive_payouts[0]["copper"] == DRIVE_PRIZE_COPPER


async def test_sqi1_drive_event_carries_leaders_and_recruits_in_contract_order(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=1), ends_at=NOW + timedelta(days=13))
    await _seed_recruit(
        db_sessionmaker,
        event_id=event_id,
        recruit_name="SoonCounter",
        inviter_name="Jaina",
        status="counting",
        invited_at=NOW - timedelta(days=5),
        joined_at=NOW - timedelta(days=5),
        qualifies_at=NOW + timedelta(days=1),
    )
    await _seed_recruit(
        db_sessionmaker,
        event_id=event_id,
        recruit_name="LaterCounter",
        inviter_name="Thrall",
        status="counting",
        invited_at=NOW - timedelta(days=4),
        joined_at=NOW - timedelta(days=4),
        qualifies_at=NOW + timedelta(days=3),
    )
    await _seed_recruit(
        db_sessionmaker,
        event_id=event_id,
        recruit_name="OlderInvite",
        inviter_name="Jaina",
        status="invited",
        invited_at=NOW - timedelta(days=2),
    )
    await _seed_recruit(
        db_sessionmaker,
        event_id=event_id,
        recruit_name="NewerInvite",
        inviter_name="Jaina",
        status="invited",
        invited_at=NOW - timedelta(hours=1),
    )
    await _seed_recruit(
        db_sessionmaker,
        event_id=event_id,
        recruit_name="OlderQualified",
        inviter_name="Thrall",
        status="qualified",
        invited_at=NOW - timedelta(days=10),
        qualified_at=NOW - timedelta(days=3),
    )
    await _seed_recruit(
        db_sessionmaker,
        event_id=event_id,
        recruit_name="NewerQualified",
        inviter_name="Thrall",
        status="qualified",
        invited_at=NOW - timedelta(days=9),
        qualified_at=NOW - timedelta(days=1),
    )
    await _seed_recruit(
        db_sessionmaker,
        event_id=event_id,
        recruit_name="Disqualified",
        inviter_name="Jaina",
        status="disqualified",
        invited_at=NOW - timedelta(days=15),
    )

    await _login_officer(member_client, discord_state, discord_id=7711)
    response = await member_client.get("/api/epgp/game-import")
    assert response.status_code == 200, response.text
    decoded = json.loads(base64.b64decode(response.json()["payload"][len("SQI1:") :]))
    events_by_id = {e["id"]: e for e in decoded["events"]}
    recruitment = events_by_id[event_id]["recruitment"]
    assert recruitment is not None

    leaders_by_inviter = {leader["inviter"]: leader for leader in recruitment["leaders"]}
    assert leaders_by_inviter["Thrall"]["qualified"] == 2
    assert leaders_by_inviter["Jaina"]["qualified"] == 0
    # Thrall has more qualified recruits than Jaina, so ranks first despite fewer total invites.
    assert recruitment["leaders"][0]["inviter"] == "Thrall"

    recruit_names = [row["recruit"] for row in recruitment["recruits"]]
    assert recruit_names == [
        "SoonCounter",  # counting, soonest qualifies_at first
        "LaterCounter",
        "NewerInvite",  # invited, newest invite first
        "OlderInvite",
        "NewerQualified",  # qualified, newest first
        "OlderQualified",
        "Disqualified",  # disqualified
    ]


async def test_sqi1_non_drive_event_has_no_recruitment(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind="other",
            title="Game Night",
            location="",
            starts_at=NOW + timedelta(days=1),
            ends_at=None,
            status="scheduled",
            notes=None,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        event_id = str(event.id)

    await _login_officer(member_client, discord_state, discord_id=7712)
    response = await member_client.get("/api/epgp/game-import")
    assert response.status_code == 200, response.text
    decoded = json.loads(base64.b64decode(response.json()["payload"][len("SQI1:") :]))
    events_by_id = {e["id"]: e for e in decoded["events"]}
    assert events_by_id[event_id]["recruitment"] is None


async def test_leaders_sorted_by_counting_when_qualified_joined_invited_tie(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """``build_leaders`` breaks a qualified/joined/invited tie by ``counting`` desc, per the new sort key."""
    event_id = await _seed_drive(db_sessionmaker, starts_at=NOW - timedelta(days=1), ends_at=NOW + timedelta(days=13))
    # Both inviters: 1 invited, 0 joined, 0 qualified; only Jaina's recruit is still counting.
    await _seed_recruit(
        db_sessionmaker,
        event_id=event_id,
        recruit_name="JainaRecruit",
        inviter_name="Jaina",
        status="counting",
        qualifies_at=NOW + timedelta(days=2),
    )
    await _seed_recruit(
        db_sessionmaker,
        event_id=event_id,
        recruit_name="AnduinRecruit",
        inviter_name="Anduin",
        status="invited",
    )

    await _login_officer(member_client, discord_state, discord_id=7713)
    response = await member_client.get(f"/api/events/{event_id}/recruitment")
    assert response.status_code == 200, response.text
    leaders = response.json()["leaders"]
    assert [leader["inviter"] for leader in leaders] == ["Jaina", "Anduin"]
