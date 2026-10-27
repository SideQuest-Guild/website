from typing import TYPE_CHECKING, Any

import pytest

from sidequest_api.domain.levels.services import MemberLevelService
from sidequest_bot.api_client import APIError, NotFoundError
from sidequest_common.models import MemberLevel
from sidequest_common.schemas import GuildConfigUpdate
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sidequest_bot.api_client import SideQuestAPI

USER_A = 111
USER_B = 222
USER_C = 333


async def test_cooldown_blocks_second_award_but_still_counts_message(api: SideQuestAPI) -> None:
    await api.update_guild_config(GUILD_ID, GuildConfigUpdate(xp_min=10, xp_max=10, xp_cooldown_seconds=60))
    first = await api.award_xp(GUILD_ID, USER_A)
    second = await api.award_xp(GUILD_ID, USER_A)

    assert first.awarded is True
    assert first.xp == 10
    assert second.awarded is False
    assert second.amount == 0
    assert second.xp == 10  # unchanged
    assert second.level == first.level

    rank = await api.get_rank(GUILD_ID, USER_A)
    assert rank.message_count == 2  # both calls counted


async def test_award_amount_within_configured_range(api: SideQuestAPI) -> None:
    await api.update_guild_config(GUILD_ID, GuildConfigUpdate(xp_min=5, xp_max=9, xp_cooldown_seconds=0))
    seen = set()
    for _ in range(30):
        result = await api.award_xp(GUILD_ID, USER_B)
        assert result.awarded is True
        seen.add(result.amount)
    assert seen <= set(range(5, 10))
    assert seen  # at least one award happened


async def test_disabled_leveling_still_counts_message_but_awards_nothing(api: SideQuestAPI) -> None:
    await api.update_guild_config(GUILD_ID, GuildConfigUpdate(leveling_enabled=False))
    result = await api.award_xp(GUILD_ID, USER_C)
    assert result.awarded is False
    assert result.amount == 0
    assert result.xp == 0
    rank = await api.get_rank(GUILD_ID, USER_C)
    assert rank.message_count == 1


async def test_level_up_crossing_multiple_levels_reports_all_earned_roles(api: SideQuestAPI) -> None:
    await api.update_guild_config(GUILD_ID, GuildConfigUpdate(xp_min=1000, xp_max=1000, xp_cooldown_seconds=0))
    await api.set_level_role(GUILD_ID, 1, 1001)
    await api.set_level_role(GUILD_ID, 2, 1002)
    await api.set_level_role(GUILD_ID, 3, 1003)

    result = await api.award_xp(GUILD_ID, 444)

    assert result.leveled_up is True
    assert result.previous_level == 0
    assert result.level >= 3
    assert {1001, 1002, 1003} <= set(result.earned_role_ids)


async def test_stacking_off_yields_remove_role_ids(api: SideQuestAPI) -> None:
    await api.update_guild_config(
        GUILD_ID, GuildConfigUpdate(xp_min=1000, xp_max=1000, xp_cooldown_seconds=0, level_roles_stack=False)
    )
    await api.set_level_role(GUILD_ID, 1, 2001)
    await api.set_level_role(GUILD_ID, 2, 2002)
    await api.set_level_role(GUILD_ID, 3, 2003)

    result = await api.award_xp(GUILD_ID, 555)

    assert result.leveled_up is True
    highest_level = max(lvl for lvl, role_id in [(1, 2001), (2, 2002), (3, 2003)] if lvl <= result.level)
    expected_remove = {role_id for lvl, role_id in [(1, 2001), (2, 2002), (3, 2003)] if lvl < highest_level}
    assert set(result.remove_role_ids) == expected_remove
    assert expected_remove  # multiple levels crossed, so there is something to remove


async def test_stacking_on_yields_no_remove_role_ids(api: SideQuestAPI) -> None:
    await api.update_guild_config(
        GUILD_ID, GuildConfigUpdate(xp_min=1000, xp_max=1000, xp_cooldown_seconds=0, level_roles_stack=True)
    )
    await api.set_level_role(GUILD_ID, 1, 3001)
    await api.set_level_role(GUILD_ID, 2, 3002)

    result = await api.award_xp(GUILD_ID, 666)

    assert result.leveled_up is True
    assert result.remove_role_ids == []


async def test_set_xp_creates_member_and_recomputes_level(api: SideQuestAPI) -> None:
    member = await api.set_xp(GUILD_ID, 777, 500)
    assert member.xp == 500
    assert member.level >= 1


async def test_rank_unknown_member_returns_zeros_not_404(api: SideQuestAPI) -> None:
    rank = await api.get_rank(GUILD_ID, 999999)
    assert rank.rank is None
    assert (rank.xp, rank.level, rank.message_count) == (0, 0, 0)
    assert rank.xp_for_next_level == 100


async def test_leaderboard_order_tiebreak_pagination_and_total(api: SideQuestAPI) -> None:
    await api.set_xp(GUILD_ID, 10, 100)
    await api.set_xp(GUILD_ID, 20, 300)
    await api.set_xp(GUILD_ID, 30, 300)  # ties with 20, lower user_id breaks tie
    await api.set_xp(GUILD_ID, 40, 0)  # zero XP excluded entirely

    page = await api.get_leaderboard(GUILD_ID, limit=2, offset=0)
    assert page.total == 3  # user 40 excluded
    assert [e.user_id for e in page.entries] == [20, 30]
    assert [e.rank for e in page.entries] == [1, 2]

    page2 = await api.get_leaderboard(GUILD_ID, limit=2, offset=2)
    assert [e.user_id for e in page2.entries] == [10]
    assert page2.entries[0].rank == 3


async def test_rank_ties_share_the_same_rank(api: SideQuestAPI) -> None:
    await api.set_xp(GUILD_ID, 51, 500)
    await api.set_xp(GUILD_ID, 52, 500)
    await api.set_xp(GUILD_ID, 53, 900)  # strictly ahead of both

    rank_a = await api.get_rank(GUILD_ID, 51)
    rank_b = await api.get_rank(GUILD_ID, 52)
    assert rank_a.rank == rank_b.rank == 2


async def test_duplicate_role_at_different_level_conflicts(api: SideQuestAPI) -> None:
    await api.set_level_role(GUILD_ID, 5, 7777)
    with pytest.raises(APIError) as excinfo:
        await api.set_level_role(GUILD_ID, 6, 7777)
    assert excinfo.value.status_code == 409


async def test_set_level_role_replaces_existing_reward_at_same_level(api: SideQuestAPI) -> None:
    await api.set_level_role(GUILD_ID, 8, 8001)
    updated = await api.set_level_role(GUILD_ID, 8, 8002)
    assert updated.role_id == 8002
    roles = await api.list_level_roles(GUILD_ID)
    assert [r for r in roles if r.level == 8] == [updated]


async def test_list_level_roles_sorted_by_level(api: SideQuestAPI) -> None:
    await api.set_level_role(GUILD_ID, 9, 9001)
    await api.set_level_role(GUILD_ID, 4, 9002)
    await api.set_level_role(GUILD_ID, 7, 9003)
    roles = await api.list_level_roles(GUILD_ID)
    assert [r.level for r in roles] == sorted(r.level for r in roles)


async def test_delete_level_role_removes_it(api: SideQuestAPI) -> None:
    await api.set_level_role(GUILD_ID, 11, 11001)
    await api.delete_level_role(GUILD_ID, 11)
    roles = await api.list_level_roles(GUILD_ID)
    assert all(r.level != 11 for r in roles)


async def test_delete_missing_level_role_404s(api: SideQuestAPI) -> None:
    with pytest.raises(NotFoundError):
        await api.delete_level_role(GUILD_ID, 999)


async def test_first_award_race_recovers_with_winners_row(
    db_sessionmaker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two requests both see no row; the loser's insert fails and it must recover with the winner's row.

    Without rolling back the loser's session after the failed insert, the follow-up ``get_one`` lookup raises
    ``PendingRollbackError`` instead of returning the winning row.
    """
    race_user_id = 777777
    async with db_sessionmaker() as winner_session, db_sessionmaker() as loser_session:
        loser = MemberLevelService(session=loser_session)
        real_lookup = loser.get_one_or_none

        async def lookup_then_lose_race(**kwargs: Any) -> MemberLevel | None:
            result = await real_lookup(**kwargs)
            # The other request inserts between our lookup and our insert.
            winner_session.add(MemberLevel(guild_id=GUILD_ID, user_id=race_user_id, xp=42))
            await winner_session.commit()
            return result

        monkeypatch.setattr(loser, "get_one_or_none", lookup_then_lose_race)
        member = await loser.get_or_create(GUILD_ID, race_user_id)

    assert member.xp == 42
