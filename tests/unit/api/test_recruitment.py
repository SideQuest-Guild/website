"""Recruitment drive qualification engine: every rule and disqualification reason in the contract, the
guild_log/recruit_payouts_paid import dedupe and idempotency, mark-paid idempotency, and payouts grouping."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_api.domain.recruitment.services import RecruitmentService
from sidequest_common.models import (
    BattlenetCharacter,
    GuildEvent,
    GuildLogEntry,
    GuildRosterSnapshot,
    Member,
    RecruitmentRecruit,
    WowCharacter,
)
from sidequest_common.schemas import RECRUIT_REWARD_COPPER, character_key
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from uuid import UUID

    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 6, 15, 0, 0, tzinfo=UTC)
RECRUIT = "Recruit-Whitemane"
INVITER = "Inviter-Whitemane"


# --- helpers ----------------------------------------------------------------------------------------------------


def _key(name: str, surname: str) -> str:
    return character_key(f"{name}-{surname}")


async def _make_event(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    starts_at: datetime,
    ends_at: datetime,
    title: str = "Recruitment Drive",
) -> UUID:
    async with db_sessionmaker() as session:
        event = GuildEvent(kind="recruitment", title=title, location="", starts_at=starts_at, ends_at=ends_at)
        session.add(event)
        await session.commit()
        return event.id


async def _add_rows(db_sessionmaker: async_sessionmaker[AsyncSession], *rows: object) -> None:
    async with db_sessionmaker() as session:
        for row in rows:
            session.add(row)
        await session.commit()


async def _evaluate(db_sessionmaker: async_sessionmaker[AsyncSession], now: datetime) -> None:
    async with db_sessionmaker() as session:
        await RecruitmentService(session).evaluate(now)


async def _row(
    db_sessionmaker: async_sessionmaker[AsyncSession], event_id: UUID, recruit_name: str = RECRUIT
) -> RecruitmentRecruit:
    async with db_sessionmaker() as session:
        return (
            await session.execute(
                select(RecruitmentRecruit).where(
                    RecruitmentRecruit.event_id == event_id, RecruitmentRecruit.recruit_name == recruit_name
                )
            )
        ).scalar_one()


def _log(
    kind: str, actor: str, at: datetime, target: str | None = None, recorder: str = "Officer-Whitemane"
) -> GuildLogEntry:
    return GuildLogEntry(kind=kind, actor=actor, target=target, at=at, recorder=recorder)


def _wow_character(name: str, surname: str, *, member_id: int | None = None) -> WowCharacter:
    return WowCharacter(
        name=name,
        surname=surname,
        realm="Whitemane",
        key=_key(name, surname),
        slug=f"{name}-{surname}",
        member_id=member_id,
    )


def _bnet_character(
    name: str,
    surname: str,
    *,
    level: int = 10,
    in_roster: bool = True,
    joined_roster_at: datetime | None = None,
    left_roster_at: datetime | None = None,
    created_at: datetime | None = None,
    blizzard_id: int = 1,
) -> BattlenetCharacter:
    kwargs: dict[str, object] = {
        "slug": _key(name, surname),
        "blizzard_id": blizzard_id,
        "name": name,
        "surname": surname,
        "level": level,
        "in_roster": in_roster,
        "joined_roster_at": joined_roster_at,
        "left_roster_at": left_roster_at,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at
    return BattlenetCharacter(**kwargs)


async def _make_member(db_sessionmaker: async_sessionmaker[AsyncSession], *, discord_id: int) -> int:
    async with db_sessionmaker() as session:
        member = Member(discord_id=discord_id, username="member")
        session.add(member)
        await session.commit()
        return member.id


async def _login_officer(client: AsyncTestClient, discord_state: dict, *, discord_id: int = 100) -> None:
    response = await login_as(client, discord_state, discord_id=discord_id, roles=[OFFICER_ROLE_ID])
    assert response.status_code == 302, response.text


def _export_string(payload: dict) -> str:
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"SQX1:{encoded}"


def _v2_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "v": 2,
        "addon_version": "1.0.0",
        "exported_at": int(NOW.timestamp()),
        "guild": "SideQuest",
        "realm": "Whitemane",
        "recorder": "Officer-Whitemane",
        "sessions": [],
        "encounters": [],
        "loot": [],
        "awards": [],
        "guild_log": [],
        "recruit_payouts_paid": [],
    }
    payload.update(overrides)
    return payload


# --- join pairing: hour-rounding, never-joined, latest-invite-wins -----------------------------------------------


async def test_joined_recruit_is_counting_before_seven_days(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    invited_at = NOW - timedelta(days=2)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=10), ends_at=NOW + timedelta(days=4))
    await _add_rows(
        db_sessionmaker, _log("invite", INVITER, invited_at, target=RECRUIT), _log("join", RECRUIT, invited_at)
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "counting"
    assert row.joined_at == invited_at


async def test_join_logged_one_hour_before_invite_still_pairs(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Both timestamps are rounded down to the hour by the game's log; a join an hour before its invite still pairs."""
    invited_at = NOW - timedelta(days=2)
    join_at = invited_at - timedelta(hours=1)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=10), ends_at=NOW + timedelta(days=4))
    await _add_rows(
        db_sessionmaker, _log("invite", INVITER, invited_at, target=RECRUIT), _log("join", RECRUIT, join_at)
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.joined_at == join_at
    assert row.status == "counting"
    assert row.reason is None


async def test_never_joined_after_forty_eight_hours(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    invited_at = NOW - timedelta(days=3)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=10), ends_at=NOW + timedelta(days=4))
    await _add_rows(db_sessionmaker, _log("invite", INVITER, invited_at, target=RECRUIT))
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "never_joined"


async def test_latest_invite_does_not_overwrite_an_already_qualified_row(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    starts_at, ends_at = NOW - timedelta(days=30), NOW - timedelta(days=10)
    invited_at = NOW - timedelta(days=25)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=ends_at)
    await _add_rows(
        db_sessionmaker,
        _log("invite", "FirstInviter-Whitemane", invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
        _wow_character("Recruit", "Whitemane"),
        _bnet_character("Recruit", "Whitemane", level=15, in_roster=True),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "qualified"
    assert row.inviter_name == "FirstInviter-Whitemane"

    # A later invite for the same recruit must not reset a row that already qualified.
    await _add_rows(
        db_sessionmaker, _log("invite", "SecondInviter-Whitemane", NOW - timedelta(days=12), target=RECRUIT)
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "qualified"
    assert row.inviter_name == "FirstInviter-Whitemane"
    assert row.invited_at == invited_at


async def test_requalify_after_quit_and_reinvite_during_drive_is_a_new_count_not_returning(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A quit then re-invite during the drive starts a new 7-day count; the earlier stint (during this same drive)
    must not be mistaken for 'returning' (in the guild before the drive)."""
    starts_at, ends_at = NOW - timedelta(days=13), NOW + timedelta(days=1)
    first_invite = NOW - timedelta(days=12)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=ends_at)
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, first_invite, target=RECRUIT),
        _log("join", RECRUIT, first_invite),
        _log("quit", RECRUIT, first_invite + timedelta(days=1)),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "left"

    second_invite = NOW - timedelta(days=6)
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, second_invite, target=RECRUIT),
        _log("join", RECRUIT, second_invite),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "counting"
    assert row.reason is None
    assert row.invited_at == second_invite
    assert row.joined_at == second_invite


# --- returning: in the guild before the drive started ---------------------------------------------------------


async def test_returning_via_earlier_guild_log_join(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    starts_at = NOW - timedelta(days=5)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=NOW + timedelta(days=9))
    await _add_rows(
        db_sessionmaker,
        _log("join", RECRUIT, NOW - timedelta(days=20)),
        _log("invite", INVITER, NOW - timedelta(days=1), target=RECRUIT),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "returning"


async def test_returning_via_earlier_guild_log_invite_targeting_them(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A guild-log join row may be missing (log retention), but an earlier invite targeting this person is still
    evidence they were already in the guild before this drive."""
    starts_at = NOW - timedelta(days=5)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=NOW + timedelta(days=9))
    await _add_rows(
        db_sessionmaker,
        _log("invite", "SomeOfficer-Whitemane", NOW - timedelta(days=20), target=RECRUIT),
        _log("invite", INVITER, NOW - timedelta(days=1), target=RECRUIT),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "returning"


async def test_returning_via_battlenet_joined_roster_at_before_starts_at(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    starts_at = NOW - timedelta(days=5)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=NOW + timedelta(days=9))
    await _add_rows(
        db_sessionmaker,
        _bnet_character("Recruit", "Whitemane", joined_roster_at=NOW - timedelta(days=30)),
        _log("invite", INVITER, NOW - timedelta(days=1), target=RECRUIT),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "returning"


async def test_returning_via_battlenet_row_in_roster_at_first_sync(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """``joined_roster_at`` is only ever set on a non-first sync; null plus a creation time before the drive means
    this character was already in the roster the very first time it was ever synced."""
    starts_at = NOW - timedelta(days=5)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=NOW + timedelta(days=9))
    await _add_rows(
        db_sessionmaker,
        _bnet_character("Recruit", "Whitemane", joined_roster_at=None, created_at=NOW - timedelta(days=30)),
        _log("invite", INVITER, NOW - timedelta(days=1), target=RECRUIT),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "returning"


async def test_returning_via_addon_roster_snapshot_created_before_starts_at(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    starts_at = NOW - timedelta(days=5)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=NOW + timedelta(days=9))
    character = _wow_character("Recruit", "Whitemane")
    async with db_sessionmaker() as session:
        session.add(character)
        await session.flush()
        session.add(
            GuildRosterSnapshot(
                character_id=character.id,
                level=5,
                last_seen_at=NOW - timedelta(days=30),
                created_at=NOW - timedelta(days=30),
            )
        )
        await session.commit()
    await _add_rows(db_sessionmaker, _log("invite", INVITER, NOW - timedelta(days=1), target=RECRUIT))
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "returning"


# --- own_alt: linked to the same member, re-checked until paid --------------------------------------------------


async def test_own_alt_disqualifies_when_recruit_and_inviter_share_a_member(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    starts_at, ends_at = NOW - timedelta(days=5), NOW + timedelta(days=9)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=ends_at)
    member_id = await _make_member(db_sessionmaker, discord_id=1)
    await _add_rows(
        db_sessionmaker,
        _wow_character("Recruit", "Whitemane", member_id=member_id),
        _wow_character("Inviter", "Whitemane", member_id=member_id),
        _log("invite", INVITER, NOW - timedelta(days=1), target=RECRUIT),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "own_alt"


async def test_own_alt_rechecked_after_qualifying_until_paid(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """A member can link an alt to their account after their recruit already qualified; that must still block the
    payout, as long as it isn't paid yet."""
    starts_at, ends_at = NOW - timedelta(days=20), NOW - timedelta(days=5)
    invited_at = NOW - timedelta(days=15)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=ends_at)
    inviter_member_id = await _make_member(db_sessionmaker, discord_id=2)
    recruit_char = _wow_character("Recruit", "Whitemane")
    await _add_rows(
        db_sessionmaker,
        recruit_char,
        _wow_character("Inviter", "Whitemane", member_id=inviter_member_id),
        _bnet_character("Recruit", "Whitemane", level=20, in_roster=True),
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "qualified"

    async with db_sessionmaker() as session:
        character = (await session.execute(select(WowCharacter).where(WowCharacter.id == recruit_char.id))).scalar_one()
        character.member_id = inviter_member_id
        await session.commit()

    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "own_alt"


# --- left: quit/removed in the 7 days, or gone by Battle.net's roster --------------------------------------------


async def test_left_via_guild_log_quit(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    invited_at = NOW - timedelta(days=9)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=10), ends_at=NOW + timedelta(days=4))
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
        _log("quit", RECRUIT, invited_at + timedelta(days=1)),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "left"


async def test_left_via_guild_log_remove(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    invited_at = NOW - timedelta(days=9)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=10), ends_at=NOW + timedelta(days=4))
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
        _log("remove", "SomeOfficer-Whitemane", invited_at + timedelta(days=1), target=RECRUIT),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "left"


async def test_left_via_battlenet_left_roster_at_inside_the_seven_days(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    invited_at = NOW - timedelta(days=9)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=10), ends_at=NOW + timedelta(days=4))
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
        _bnet_character("Recruit", "Whitemane", in_roster=False, left_roster_at=invited_at + timedelta(days=1)),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "left"


async def test_left_when_not_in_guild_once_the_seven_days_are_up_with_no_log_entry(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """No quit/remove log row and no recorded ``left_roster_at``, but Battle.net simply doesn't have them in the
    guild any more once the 7 days are up."""
    invited_at = NOW - timedelta(days=10)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=15), ends_at=NOW - timedelta(days=1))
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
        _bnet_character("Recruit", "Whitemane", in_roster=False, left_roster_at=None),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "left"


# --- low_level / qualified: level at day 7 -----------------------------------------------------------------------


async def test_low_level_disqualifies_at_day_seven(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    invited_at = NOW - timedelta(days=10)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=15), ends_at=NOW - timedelta(days=1))
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
        _wow_character("Recruit", "Whitemane"),
        _bnet_character("Recruit", "Whitemane", level=5, in_roster=True),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "disqualified"
    assert row.reason == "low_level"
    assert row.level == 5


async def test_qualifies_at_minimum_level_on_day_seven(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    invited_at = NOW - timedelta(days=10)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=15), ends_at=NOW - timedelta(days=1))
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
        _wow_character("Recruit", "Whitemane"),
        _bnet_character("Recruit", "Whitemane", level=10, in_roster=True),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "qualified"
    assert row.reason is None
    assert row.reward_copper == RECRUIT_REWARD_COPPER
    assert row.qualified_at == NOW


async def test_qualifies_with_a_level_only_battlenet_knows(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """No officer's addon has swept the recruit into the roster yet; Battle.net's roster level is enough."""
    invited_at = NOW - timedelta(days=10)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=15), ends_at=NOW - timedelta(days=1))
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
        _bnet_character("Recruit", "Whitemane", level=12, in_roster=True),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "qualified"
    assert row.level == 12


async def test_late_finisher_after_settles_at_still_qualifies(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A recruit whose 7 days finish later than ``settles_at`` still qualifies when they finish."""
    starts_at, ends_at = NOW - timedelta(days=20), NOW - timedelta(days=10)
    invited_at = ends_at  # the last possible invite within the drive window
    joined_at = ends_at + timedelta(days=2)  # within the 48h join window, but after the drive ended
    qualifies_at = joined_at + timedelta(days=7)  # settles_at is ends_at + 7 days; this is 2 days later
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=ends_at)
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, joined_at),
        _wow_character("Recruit", "Whitemane"),
        _bnet_character("Recruit", "Whitemane", level=10, in_roster=True),
    )

    before_finish = qualifies_at - timedelta(days=1)
    await _evaluate(db_sessionmaker, before_finish)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "counting"  # settles_at has already passed, but they haven't finished their 7 days yet

    await _evaluate(db_sessionmaker, qualifies_at)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "qualified"


# --- idempotency: paid rows are frozen, mark_paid doesn't double-pay ----------------------------------------------


async def test_paid_row_is_never_unqualified_by_a_later_evaluation(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    starts_at, ends_at = NOW - timedelta(days=20), NOW - timedelta(days=10)
    invited_at = NOW - timedelta(days=15)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=ends_at)
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
        _wow_character("Recruit", "Whitemane"),
        _bnet_character("Recruit", "Whitemane", level=10, in_roster=True),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "qualified"

    async with db_sessionmaker() as session:
        await RecruitmentService(session).mark_paid(event_id, INVITER, "PayingOfficer", now=NOW)

    # Mutate the underlying evidence to what would normally disqualify the row, then re-evaluate.
    await _add_rows(db_sessionmaker, _log("quit", RECRUIT, invited_at + timedelta(days=1)))
    async with db_sessionmaker() as session:
        character = (
            await session.execute(
                select(BattlenetCharacter).where(BattlenetCharacter.slug == _key("Recruit", "Whitemane"))
            )
        ).scalar_one()
        character.level = 1
        await session.commit()
    await _evaluate(db_sessionmaker, NOW + timedelta(days=5))

    row = await _row(db_sessionmaker, event_id)
    assert row.status == "qualified"
    assert row.paid_at is not None
    assert row.paid_by == "PayingOfficer"


async def test_mark_paid_is_idempotent(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    starts_at, ends_at = NOW - timedelta(days=20), NOW - timedelta(days=10)
    invited_at = NOW - timedelta(days=15)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=ends_at)
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
        _wow_character("Recruit", "Whitemane"),
        _bnet_character("Recruit", "Whitemane", level=10, in_roster=True),
    )
    await _evaluate(db_sessionmaker, NOW)

    async with db_sessionmaker() as session:
        await RecruitmentService(session).mark_paid(event_id, INVITER, "FirstOfficer", now=NOW)
    async with db_sessionmaker() as session:
        await RecruitmentService(session).mark_paid(event_id, INVITER, "SecondOfficer", now=NOW + timedelta(hours=1))

    row = await _row(db_sessionmaker, event_id)
    assert row.paid_by == "FirstOfficer"
    assert row.paid_at == NOW


# --- payouts: grouping per inviter, mixed paid/unpaid -------------------------------------------------------------


async def test_list_payouts_groups_per_inviter_and_excludes_already_paid_recruits(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    starts_at = NOW - timedelta(days=30)
    ends_at = NOW - timedelta(days=16)  # settles_at = ends_at + 7d, already settled
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=ends_at)
    await _add_rows(
        db_sessionmaker,
        RecruitmentRecruit(
            event_id=event_id,
            recruit_name="PaidRecruit-Whitemane",
            inviter_name=INVITER,
            invited_at=NOW - timedelta(days=29),
            joined_at=NOW - timedelta(days=29),
            qualifies_at=NOW - timedelta(days=22),
            status="qualified",
            qualified_at=NOW - timedelta(days=22),
            reward_copper=RECRUIT_REWARD_COPPER,
            paid_at=NOW - timedelta(days=20),
            paid_by="OldOfficer",
            paid_via="site",
        ),
        RecruitmentRecruit(
            event_id=event_id,
            recruit_name="UnpaidRecruit-Whitemane",
            inviter_name=INVITER,
            invited_at=NOW - timedelta(days=28),
            joined_at=NOW - timedelta(days=28),
            qualifies_at=NOW - timedelta(days=21),
            status="qualified",
            qualified_at=NOW - timedelta(days=21),
            reward_copper=RECRUIT_REWARD_COPPER,
        ),
    )
    async with db_sessionmaker() as session:
        payouts = await RecruitmentService(session).list_payouts(now=NOW)

    matching = [payout for payout in payouts if payout.event_id == event_id]
    assert len(matching) == 1
    payout = matching[0]
    assert payout.inviter == INVITER
    assert payout.recruits == ["UnpaidRecruit-Whitemane"]
    assert payout.copper == RECRUIT_REWARD_COPPER
    assert payout.paid_at is None


# --- import: guild_log dedupe, recruit_payouts_paid idempotency --------------------------------------------------


async def test_guild_log_reimport_shifted_by_up_to_two_hours_creates_no_new_rows(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state)
    at = int(NOW.timestamp())
    first = _v2_payload(guild_log=[{"kind": "invite", "actor": INVITER, "target": RECRUIT, "at": at}])
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(first)})
    assert response.status_code == 200, response.text
    assert response.json()["guild_log"] == {"new": 1, "merged": 0}

    shifted = _v2_payload(guild_log=[{"kind": "invite", "actor": INVITER, "target": RECRUIT, "at": at + 2 * 3600}])
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(shifted)})
    assert response.status_code == 200, response.text
    assert response.json()["guild_log"] == {"new": 0, "merged": 1}

    async with db_sessionmaker() as session:
        rows = (await session.execute(select(GuildLogEntry))).scalars().all()
        assert len(rows) == 1


async def test_recruit_payouts_paid_import_is_idempotent(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=20), ends_at=NOW - timedelta(days=5))
    await _add_rows(
        db_sessionmaker,
        RecruitmentRecruit(
            event_id=event_id,
            recruit_name=RECRUIT,
            inviter_name=INVITER,
            invited_at=NOW - timedelta(days=19),
            joined_at=NOW - timedelta(days=19),
            qualifies_at=NOW - timedelta(days=12),
            status="qualified",
            qualified_at=NOW - timedelta(days=12),
            reward_copper=RECRUIT_REWARD_COPPER,
        ),
    )
    await _login_officer(member_client, discord_state)
    at = int(NOW.timestamp())
    payload = _v2_payload(
        recruit_payouts_paid=[
            {
                "event_id": str(event_id),
                "inviter": INVITER,
                "copper": RECRUIT_REWARD_COPPER,
                "at": at,
                "officer": "Officer-Whitemane",
            }
        ]
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    assert response.json()["recruit_payouts_paid"] == {"new": 1, "already_paid": 0}

    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    assert response.json()["recruit_payouts_paid"] == {"new": 0, "already_paid": 1}

    row = await _row(db_sessionmaker, event_id)
    assert row.paid_at is not None
    assert row.paid_via == "addon"


# --- real addon fixture -------------------------------------------------------------------------------------------


async def test_real_guild_log_fixture_imports_successfully_and_is_idempotent(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _login_officer(member_client, discord_state)
    raw_text = (FIXTURES_DIR / "export_v2_guild_log.txt").read_text().strip()

    response = await member_client.post("/api/epgp/imports", json={"payload": raw_text})
    assert response.status_code == 200, response.text
    assert response.json()["guild_log"] == {"new": 1, "merged": 0}

    response = await member_client.post("/api/epgp/imports", json={"payload": raw_text})
    assert response.status_code == 200, response.text
    assert response.json()["guild_log"] == {"new": 0, "merged": 1}

    async with db_sessionmaker() as session:
        rows = (await session.execute(select(GuildLogEntry))).scalars().all()
        assert len(rows) == 1
        assert rows[0].kind == "invite"
        assert rows[0].actor == "Officer1-Whitemane"
        assert rows[0].target == "Newbie-Whitemane"


# --- follow-up: addon payout only covers what was qualified by the time it was mailed ---------------------------


async def test_addon_payout_only_marks_recruits_qualified_by_the_time_it_was_mailed(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=20), ends_at=NOW - timedelta(days=5))
    mailed_at = NOW - timedelta(days=3)
    await _add_rows(
        db_sessionmaker,
        RecruitmentRecruit(
            event_id=event_id,
            recruit_name="EarlyRecruit-Whitemane",
            inviter_name=INVITER,
            invited_at=NOW - timedelta(days=19),
            joined_at=NOW - timedelta(days=19),
            qualifies_at=NOW - timedelta(days=12),
            status="qualified",
            qualified_at=NOW - timedelta(days=10),  # qualified before the mail was sent
            reward_copper=RECRUIT_REWARD_COPPER,
        ),
        RecruitmentRecruit(
            event_id=event_id,
            recruit_name="LateRecruit-Whitemane",
            inviter_name=INVITER,
            invited_at=NOW - timedelta(days=18),
            joined_at=NOW - timedelta(days=18),
            qualifies_at=NOW - timedelta(days=11),
            status="qualified",
            qualified_at=NOW - timedelta(days=1),  # qualified after the mail was already sent
            reward_copper=RECRUIT_REWARD_COPPER,
        ),
    )
    await _login_officer(member_client, discord_state)
    payload = _v2_payload(
        recruit_payouts_paid=[
            {
                "event_id": str(event_id),
                "inviter": INVITER,
                "copper": RECRUIT_REWARD_COPPER,  # 1g: the mail covered exactly one recruit
                "at": int(mailed_at.timestamp()),
                "officer": "Officer-Whitemane",
            }
        ]
    )
    response = await member_client.post("/api/epgp/imports", json={"payload": _export_string(payload)})
    assert response.status_code == 200, response.text
    assert response.json()["recruit_payouts_paid"] == {"new": 1, "already_paid": 0}

    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(RecruitmentRecruit).where(RecruitmentRecruit.event_id == event_id)))
            .scalars()
            .all()
        )
    by_name = {row.recruit_name: row for row in rows}
    assert by_name["EarlyRecruit-Whitemane"].paid_at is not None
    assert by_name["LateRecruit-Whitemane"].paid_at is None


# --- follow-up: surname-less guild-log names (GetGuildEventInfo may omit the surname) ----------------------------


async def test_surname_less_guild_log_name_resolves_to_the_single_matching_character(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    starts_at, ends_at = NOW - timedelta(days=15), NOW - timedelta(days=1)
    invited_at = NOW - timedelta(days=10)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=ends_at)
    await _add_rows(
        db_sessionmaker,
        _wow_character("Recruit", "Whitemane"),
        _bnet_character("Recruit", "Whitemane", level=10, in_roster=True),
        _log("invite", INVITER, invited_at, target="Recruit"),  # bare name, no surname
        _log("join", "Recruit", invited_at),  # the join log is bare too, consistently
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id, recruit_name=RECRUIT)
    assert row.recruit_name == RECRUIT
    assert row.status == "qualified"


async def test_ambiguous_surname_less_guild_log_name_stays_unresolved(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    starts_at, ends_at = NOW - timedelta(days=15), NOW - timedelta(days=1)
    invited_at = NOW - timedelta(days=10)
    event_id = await _make_event(db_sessionmaker, starts_at=starts_at, ends_at=ends_at)
    await _add_rows(
        db_sessionmaker,
        _bnet_character("Ambig", "Whitemane", level=10, in_roster=True, blizzard_id=10),
        _bnet_character("Ambig", "Faerlina", level=10, in_roster=True, blizzard_id=11),
        _log("invite", INVITER, invited_at, target="Ambig"),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id, recruit_name="Ambig")
    assert row.recruit_name == "Ambig"
    assert row.recruit_character_id is None


# --- follow-up: unknown level is not low_level -------------------------------------------------------------------


async def test_unknown_level_at_day_seven_stays_counting_not_low_level(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    invited_at = NOW - timedelta(days=10)
    event_id = await _make_event(db_sessionmaker, starts_at=NOW - timedelta(days=15), ends_at=NOW - timedelta(days=1))
    await _add_rows(
        db_sessionmaker,
        _log("invite", INVITER, invited_at, target=RECRUIT),
        _log("join", RECRUIT, invited_at),
    )
    await _evaluate(db_sessionmaker, NOW)
    row = await _row(db_sessionmaker, event_id)
    assert row.status == "counting"
    assert row.reason is None
    assert row.level is None
