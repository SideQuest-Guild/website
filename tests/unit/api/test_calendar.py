"""``/api/me/calendar`` (token issuance/rotation) and ``/api/calendar/<token>.ics`` (the public feed)."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import EventSignup, GuildEvent, Member
from tests.unit.api.conftest import login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _seed_event(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    discord_id: int,
    *,
    title: str = "Molten Core",
    kind: str = "raid",
    starts_at: datetime | None = None,
    status: str = "scheduled",
    notes: str | None = None,
    signup: bool = True,
) -> str:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind=kind,
            title=title,
            location="Molten Core",
            starts_at=starts_at or (datetime.now(UTC) + timedelta(days=1)),
            size=40,
            status=status,
            notes=notes,
        )
        session.add(event)
        await session.flush()
        if signup:
            member = (await session.execute(select(Member).where(Member.discord_id == discord_id))).scalar_one_or_none()
            if member is not None:
                session.add(
                    EventSignup(
                        event_id=event.id,
                        member_id=member.id,
                        character="Oakenshield",
                        wow_class="warrior",
                        role="tank",
                        status="signed",
                    )
                )
        await session.commit()
        await session.refresh(event)
        return str(event.id)


async def test_calendar_link_requires_sign_in(member_client: AsyncTestClient) -> None:
    response = await member_client.get("/api/me/calendar")
    assert response.status_code == 401


async def test_calendar_link_lazily_creates_and_returns_a_stable_token(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=5001)
    first = await member_client.get("/api/me/calendar")
    assert first.status_code == 200
    body = first.json()
    assert body["url"] == f"http://localhost:8000/api/calendar/{body['token']}.ics"
    assert len(body["token"]) >= 20

    second = await member_client.get("/api/me/calendar")
    assert second.json()["token"] == body["token"]


async def test_rotating_the_token_invalidates_the_old_link(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=5002)
    old_token = (await member_client.get("/api/me/calendar")).json()["token"]

    rotated = await member_client.post("/api/me/calendar/rotate")
    assert rotated.status_code == 200
    new_token = rotated.json()["token"]
    assert new_token != old_token

    assert (await member_client.get(f"/api/calendar/{old_token}.ics")).status_code == 404
    assert (await member_client.get(f"/api/calendar/{new_token}.ics")).status_code == 200


async def test_unknown_token_404s(member_client: AsyncTestClient) -> None:
    response = await member_client.get("/api/calendar/not-a-real-token.ics")
    assert response.status_code == 404


async def test_feed_carries_no_set_cookie_and_is_marked_private(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=5003)
    token = (await member_client.get("/api/me/calendar")).json()["token"]
    response = await member_client.get(f"/api/calendar/{token}.ics")
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "private"
    assert response.headers["content-type"].startswith("text/calendar")


async def test_feed_titles_signup_and_url(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=5004)
    event_id = await _seed_event(db_sessionmaker, 5004)
    token = (await member_client.get("/api/me/calendar")).json()["token"]
    body = (await member_client.get(f"/api/calendar/{token}.ics")).text
    unfolded = body.replace("\r\n ", "")

    assert "BEGIN:VCALENDAR" in unfolded
    assert "X-WR-CALNAME:SideQuest" in unfolded
    assert "SUMMARY:Molten Core (Raid)" in unfolded
    assert "Going as Oakenshield" in unfolded
    assert f"/events/detail/?id={event_id}" in unfolded
    assert f"UID:{event_id}@sidequest-guild.com" in unfolded


async def test_feed_carries_sidequest_kind_and_signup_properties(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=5009)
    await _seed_event(db_sessionmaker, 5009, kind="raid")
    token = (await member_client.get("/api/me/calendar")).json()["token"]
    body = (await member_client.get(f"/api/calendar/{token}.ics")).text
    unfolded = body.replace("\r\n ", "")

    assert "X-SIDEQUEST-KIND:raid" in unfolded
    assert "X-SIDEQUEST-SIGNUP:signed" in unfolded


async def test_feed_omits_signup_property_without_a_signup(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=5010)
    await _seed_event(db_sessionmaker, 5010, kind="dungeon", signup=False)
    token = (await member_client.get("/api/me/calendar")).json()["token"]
    body = (await member_client.get(f"/api/calendar/{token}.ics")).text
    unfolded = body.replace("\r\n ", "")

    assert "X-SIDEQUEST-KIND:dungeon" in unfolded
    assert "X-SIDEQUEST-SIGNUP" not in unfolded


async def test_cancelled_event_gets_status_cancelled(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=5005)
    await _seed_event(db_sessionmaker, 5005, status="cancelled", signup=False)
    token = (await member_client.get("/api/me/calendar")).json()["token"]
    body = (await member_client.get(f"/api/calendar/{token}.ics")).text
    assert "STATUS:CANCELLED" in body


async def test_special_characters_are_escaped(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=5006)
    await _seed_event(
        db_sessionmaker,
        5006,
        title="Onyxia; the Dragon, Queen",
        notes="Bring flasks\nand food",
        signup=False,
    )
    token = (await member_client.get("/api/me/calendar")).json()["token"]
    body = (await member_client.get(f"/api/calendar/{token}.ics")).text
    assert "Onyxia\\; the Dragon\\, Queen" in body
    assert "Bring flasks\\nand food" in body


async def test_long_summary_line_is_folded(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    long_title = "Molten Core: Ragnaros, Majordomo Executus and the whole Firelord's court, every single boss"
    await login_as(member_client, discord_state, discord_id=5007)
    await _seed_event(db_sessionmaker, 5007, title=long_title, signup=False)
    token = (await member_client.get("/api/me/calendar")).json()["token"]
    body = (await member_client.get(f"/api/calendar/{token}.ics")).text
    lines = body.split("\r\n")
    # A folded content line continues on the next physical line, which starts with a single space.
    assert any(line.startswith(" ") for line in lines)
    for line in lines:
        if line.startswith(" "):
            continue
        assert len(line.encode("utf-8")) <= 75


async def test_feed_excludes_events_older_than_thirty_days(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=5008)
    old_title = "Ancient Raid Night"
    await _seed_event(
        db_sessionmaker,
        5008,
        title=old_title,
        starts_at=datetime.now(UTC) - timedelta(days=45),
        signup=False,
    )
    token = (await member_client.get("/api/me/calendar")).json()["token"]
    body = (await member_client.get(f"/api/calendar/{token}.ics")).text
    assert old_title not in body
