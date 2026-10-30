"""``DELETE /api/me``: deletes the member and everything that belongs to them, and clears the session cookie."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import (
    EventSignup,
    EventSignupActivity,
    EventVoicePresence,
    GuildEvent,
    Member,
    MemberLevel,
    MemberRoleReset,
    ModCase,
    OfficerAudit,
)
from tests.unit.api.conftest import link_battlenet, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _seed_event(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    title: str = "Molten Core",
) -> str:
    async with db_sessionmaker() as session:
        event = GuildEvent(
            kind="raid",
            title=title,
            location="Molten Core",
            starts_at=datetime.now(UTC) + timedelta(days=1),
            size=40,
            status="scheduled",
            notes=None,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return str(event.id)


def _signup_body(character: str = "Thrall", role: str = "dps", status: str = "signed") -> dict:
    return {"character": character, "class": "warrior", "role": role, "status": status, "comment": None}


async def test_delete_account_requires_sign_in(member_client: AsyncTestClient) -> None:
    response = await member_client.delete("/api/me")
    assert response.status_code == 401


async def test_delete_account_removes_member_and_own_signups_only(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)

    await login_as(member_client, discord_state, discord_id=9001, username="deleter", roles=[])
    me_response = await member_client.get("/api/me")
    deleter_id = me_response.json()["id"]
    await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body(character="Deleter"))

    await login_as(member_client, discord_state, discord_id=9002, username="survivor", roles=[])
    await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body(character="Survivor"))

    await login_as(member_client, discord_state, discord_id=9001, username="deleter", roles=[])
    delete_response = await member_client.delete("/api/me")
    assert delete_response.status_code == 204

    async with db_sessionmaker() as session:
        assert await session.get(Member, deleter_id) is None
        remaining_signups = (await session.execute(select(EventSignup))).scalars().all()
        assert len(remaining_signups) == 1
        assert remaining_signups[0].character == "Survivor"

    await login_as(member_client, discord_state, discord_id=9002, username="survivor", roles=[])
    event_detail = await member_client.get(f"/api/events/{event_id}")
    assert event_detail.json()["counts"]["dps"] == 1
    assert event_detail.json()["counts"]["signed"] == 1
    assert [s["character"] for s in event_detail.json()["signups"]] == ["Survivor"]


async def test_delete_account_clears_session_cookie(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=9003)
    assert (await member_client.delete("/api/me")).status_code == 204
    assert (await member_client.get("/api/me")).status_code == 401


async def test_sign_in_again_after_deletion_creates_a_fresh_member(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=9004, username="phoenix")
    assert (await member_client.delete("/api/me")).status_code == 204

    await login_as(member_client, discord_state, discord_id=9004, username="phoenix")
    me_response = await member_client.get("/api/me")
    assert me_response.status_code == 200
    assert me_response.json()["discord_id"] == "9004"

    async with db_sessionmaker() as session:
        rows = (await session.execute(select(Member).where(Member.discord_id == 9004))).scalars().all()
        assert len(rows) == 1


async def test_unlink_battlenet_clears_id_tag_and_linked_at(
    member_client: AsyncTestClient,
    discord_state: dict,
    battlenet_state: dict,
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await login_as(member_client, discord_state, discord_id=9005)
    await link_battlenet(member_client, battlenet_state, account_id=4242, battletag="Linked#4242")
    me_id = (await member_client.get("/api/me")).json()["id"]

    assert (await member_client.post("/auth/battlenet/unlink")).status_code == 204

    async with db_sessionmaker() as session:
        member = await session.get(Member, me_id)
        assert member is not None
        assert member.battlenet_id is None
        assert member.battletag is None
        assert member.battlenet_linked_at is None


async def test_delete_account_removes_event_signup_activity_by_discord_id(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=9006, username="activity-owner", roles=[])
    await member_client.put(f"/api/events/{event_id}/signup", json=_signup_body(character="Jaina"))

    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(EventSignupActivity).where(EventSignupActivity.discord_id == 9006)))
            .scalars()
            .all()
        )
        assert len(rows) == 1

    assert (await member_client.delete("/api/me")).status_code == 204

    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(EventSignupActivity).where(EventSignupActivity.discord_id == 9006)))
            .scalars()
            .all()
        )
        assert rows == []


async def test_delete_account_removes_event_voice_presence_by_discord_id(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _seed_event(db_sessionmaker)
    await login_as(member_client, discord_state, discord_id=9011, username="voice-haver", roles=[])

    async with db_sessionmaker() as session:
        session.add(EventVoicePresence(event_id=event_id, discord_id=9011, minutes=42))
        await session.commit()

    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(EventVoicePresence).where(EventVoicePresence.discord_id == 9011)))
            .scalars()
            .all()
        )
        assert len(rows) == 1

    assert (await member_client.delete("/api/me")).status_code == 204

    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(EventVoicePresence).where(EventVoicePresence.discord_id == 9011)))
            .scalars()
            .all()
        )
        assert rows == []


async def test_delete_account_nulls_officer_audit_actor_but_keeps_actor_name(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=9007, username="Captain Officer", roles=[])
    actor_id = (await member_client.get("/api/me")).json()["id"]

    async with db_sessionmaker() as session:
        session.add(
            OfficerAudit(
                actor_member_id=actor_id,
                actor_name="Captain Officer",
                action="event.create",
                subject_type="event",
                subject_id=None,
                summary='Created raid "Molten Core" for Nov 6',
            )
        )
        await session.commit()

    assert (await member_client.delete("/api/me")).status_code == 204

    async with db_sessionmaker() as session:
        audit = (
            (await session.execute(select(OfficerAudit).where(OfficerAudit.action == "event.create"))).scalars().one()
        )
        assert audit.actor_member_id is None
        assert audit.actor_name == "Captain Officer"


async def test_delete_account_removes_member_level_rows_in_every_guild_but_keeps_other_members_xp_and_mod_cases(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=9008, username="xp-haver", roles=[])

    async with db_sessionmaker() as session:
        session.add_all(
            [
                MemberLevel(guild_id=1564671275316543508, user_id=9008, xp=500, level=5, message_count=50),
                MemberLevel(guild_id=424242, user_id=9008, xp=10, level=1, message_count=1),
                MemberLevel(guild_id=1564671275316543508, user_id=9009, xp=999, level=9, message_count=99),
                ModCase(
                    guild_id=1564671275316543508,
                    case_number=1,
                    action="warn",
                    user_id=9008,
                    moderator_id=9009,
                    reason="Spamming",
                ),
            ]
        )
        await session.commit()

    assert (await member_client.delete("/api/me")).status_code == 204

    async with db_sessionmaker() as session:
        deleted_user_rows = (
            (await session.execute(select(MemberLevel).where(MemberLevel.user_id == 9008))).scalars().all()
        )
        assert deleted_user_rows == []

        other_user_rows = (
            (await session.execute(select(MemberLevel).where(MemberLevel.user_id == 9009))).scalars().all()
        )
        assert len(other_user_rows) == 1
        assert other_user_rows[0].xp == 999

        mod_cases = (await session.execute(select(ModCase))).scalars().all()
        assert len(mod_cases) == 1
        assert mod_cases[0].user_id == 9008
        assert mod_cases[0].reason == "Spamming"


async def test_delete_account_writes_pending_role_reset(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=9010, username="role-haver")

    assert (await member_client.delete("/api/me")).status_code == 204

    async with db_sessionmaker() as session:
        resets = (await session.execute(select(MemberRoleReset))).scalars().all()
        assert len(resets) == 1
        assert resets[0].discord_id == 9010
        assert resets[0].done_at is None
