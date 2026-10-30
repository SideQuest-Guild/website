from typing import TYPE_CHECKING, Any

import pytest

from sidequest_api.domain.levels.services import MemberLevelService
from sidequest_common.models import MemberLevel
from sidequest_common.schemas import GuildConfigUpdate, LevelRoleSchema
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from httpx import Response
    from litestar import Litestar
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

USER_A = 111
USER_B = 222
USER_C = 333


async def _update_guild_config(client: AsyncTestClient[Litestar], guild_id: int, **changes: Any) -> dict:
    body = GuildConfigUpdate(**changes).model_dump(mode="json", exclude_unset=True)
    response = await client.patch(f"/api/guilds/{guild_id}/config", json=body)
    assert response.status_code == 200
    return response.json()


async def _award_xp(client: AsyncTestClient[Litestar], guild_id: int, user_id: int) -> dict:
    response = await client.post(f"/api/guilds/{guild_id}/members/{user_id}/xp")
    assert response.status_code == 200
    return response.json()


async def _set_xp(client: AsyncTestClient[Litestar], guild_id: int, user_id: int, xp: int) -> dict:
    response = await client.put(f"/api/guilds/{guild_id}/members/{user_id}/xp", json={"xp": xp})
    assert response.status_code == 200
    return response.json()


async def _get_rank(client: AsyncTestClient[Litestar], guild_id: int, user_id: int) -> dict:
    response = await client.get(f"/api/guilds/{guild_id}/members/{user_id}/rank")
    assert response.status_code == 200
    return response.json()


async def _get_leaderboard(
    client: AsyncTestClient[Litestar], guild_id: int, *, limit: int = 10, offset: int = 0
) -> dict:
    response = await client.get(f"/api/guilds/{guild_id}/leaderboard", params={"limit": limit, "offset": offset})
    assert response.status_code == 200
    return response.json()


async def _set_level_role(client: AsyncTestClient[Litestar], guild_id: int, level: int, role_id: int) -> Response:
    return await client.put(f"/api/guilds/{guild_id}/level-roles/{level}", json={"role_id": role_id})


async def _list_level_roles(client: AsyncTestClient[Litestar], guild_id: int) -> list[LevelRoleSchema]:
    response = await client.get(f"/api/guilds/{guild_id}/level-roles")
    assert response.status_code == 200
    return [LevelRoleSchema.model_validate(role) for role in response.json()]


async def test_cooldown_blocks_second_award_but_still_counts_message(client: AsyncTestClient[Litestar]) -> None:
    await _update_guild_config(client, GUILD_ID, xp_min=10, xp_max=10, xp_cooldown_seconds=60)
    first = await _award_xp(client, GUILD_ID, USER_A)
    second = await _award_xp(client, GUILD_ID, USER_A)

    assert first["awarded"] is True
    assert first["xp"] == 10
    assert second["awarded"] is False
    assert second["amount"] == 0
    assert second["xp"] == 10  # unchanged
    assert second["level"] == first["level"]

    rank = await _get_rank(client, GUILD_ID, USER_A)
    assert rank["message_count"] == 2  # both calls counted


async def test_award_amount_within_configured_range(client: AsyncTestClient[Litestar]) -> None:
    await _update_guild_config(client, GUILD_ID, xp_min=5, xp_max=9, xp_cooldown_seconds=0)
    seen = set()
    for _ in range(30):
        result = await _award_xp(client, GUILD_ID, USER_B)
        assert result["awarded"] is True
        seen.add(result["amount"])
    assert seen <= set(range(5, 10))
    assert seen  # at least one award happened


async def test_disabled_leveling_still_counts_message_but_awards_nothing(client: AsyncTestClient[Litestar]) -> None:
    await _update_guild_config(client, GUILD_ID, leveling_enabled=False)
    result = await _award_xp(client, GUILD_ID, USER_C)
    assert result["awarded"] is False
    assert result["amount"] == 0
    assert result["xp"] == 0
    rank = await _get_rank(client, GUILD_ID, USER_C)
    assert rank["message_count"] == 1


async def test_level_up_crossing_multiple_levels_reports_all_earned_roles(client: AsyncTestClient[Litestar]) -> None:
    await _update_guild_config(client, GUILD_ID, xp_min=1000, xp_max=1000, xp_cooldown_seconds=0)
    await _set_level_role(client, GUILD_ID, 1, 1001)
    await _set_level_role(client, GUILD_ID, 2, 1002)
    await _set_level_role(client, GUILD_ID, 3, 1003)

    result = await _award_xp(client, GUILD_ID, 444)

    assert result["leveled_up"] is True
    assert result["previous_level"] == 0
    assert result["level"] >= 3
    assert {1001, 1002, 1003} <= set(result["earned_role_ids"])


async def test_stacking_off_yields_remove_role_ids(client: AsyncTestClient[Litestar]) -> None:
    await _update_guild_config(
        client, GUILD_ID, xp_min=1000, xp_max=1000, xp_cooldown_seconds=0, level_roles_stack=False
    )
    await _set_level_role(client, GUILD_ID, 1, 2001)
    await _set_level_role(client, GUILD_ID, 2, 2002)
    await _set_level_role(client, GUILD_ID, 3, 2003)

    result = await _award_xp(client, GUILD_ID, 555)

    assert result["leveled_up"] is True
    highest_level = max(lvl for lvl, role_id in [(1, 2001), (2, 2002), (3, 2003)] if lvl <= result["level"])
    expected_remove = {role_id for lvl, role_id in [(1, 2001), (2, 2002), (3, 2003)] if lvl < highest_level}
    assert set(result["remove_role_ids"]) == expected_remove
    assert expected_remove  # multiple levels crossed, so there is something to remove


async def test_stacking_on_yields_no_remove_role_ids(client: AsyncTestClient[Litestar]) -> None:
    await _update_guild_config(
        client, GUILD_ID, xp_min=1000, xp_max=1000, xp_cooldown_seconds=0, level_roles_stack=True
    )
    await _set_level_role(client, GUILD_ID, 1, 3001)
    await _set_level_role(client, GUILD_ID, 2, 3002)

    result = await _award_xp(client, GUILD_ID, 666)

    assert result["leveled_up"] is True
    assert result["remove_role_ids"] == []


async def test_set_xp_creates_member_and_recomputes_level(client: AsyncTestClient[Litestar]) -> None:
    member = await _set_xp(client, GUILD_ID, 777, 500)
    assert member["xp"] == 500
    assert member["level"] >= 1


async def test_rank_unknown_member_returns_zeros_not_404(client: AsyncTestClient[Litestar]) -> None:
    rank = await _get_rank(client, GUILD_ID, 999999)
    assert rank["rank"] is None
    assert (rank["xp"], rank["level"], rank["message_count"]) == (0, 0, 0)
    assert rank["xp_for_next_level"] == 100


async def test_leaderboard_order_tiebreak_pagination_and_total(client: AsyncTestClient[Litestar]) -> None:
    await _set_xp(client, GUILD_ID, 10, 100)
    await _set_xp(client, GUILD_ID, 20, 300)
    await _set_xp(client, GUILD_ID, 30, 300)  # ties with 20, lower user_id breaks tie
    await _set_xp(client, GUILD_ID, 40, 0)  # zero XP excluded entirely

    page = await _get_leaderboard(client, GUILD_ID, limit=2, offset=0)
    assert page["total"] == 3  # user 40 excluded
    assert [e["user_id"] for e in page["entries"]] == [20, 30]
    assert [e["rank"] for e in page["entries"]] == [1, 2]

    page2 = await _get_leaderboard(client, GUILD_ID, limit=2, offset=2)
    assert [e["user_id"] for e in page2["entries"]] == [10]
    assert page2["entries"][0]["rank"] == 3


async def test_rank_ties_share_the_same_rank(client: AsyncTestClient[Litestar]) -> None:
    await _set_xp(client, GUILD_ID, 51, 500)
    await _set_xp(client, GUILD_ID, 52, 500)
    await _set_xp(client, GUILD_ID, 53, 900)  # strictly ahead of both

    rank_a = await _get_rank(client, GUILD_ID, 51)
    rank_b = await _get_rank(client, GUILD_ID, 52)
    assert rank_a["rank"] == rank_b["rank"] == 2


async def test_duplicate_role_at_different_level_conflicts(client: AsyncTestClient[Litestar]) -> None:
    await _set_level_role(client, GUILD_ID, 5, 7777)
    response = await _set_level_role(client, GUILD_ID, 6, 7777)
    assert response.status_code == 409


async def test_set_level_role_replaces_existing_reward_at_same_level(client: AsyncTestClient[Litestar]) -> None:
    await _set_level_role(client, GUILD_ID, 8, 8001)
    updated_response = await _set_level_role(client, GUILD_ID, 8, 8002)
    assert updated_response.status_code == 200
    updated = LevelRoleSchema.model_validate(updated_response.json())
    assert updated.role_id == 8002
    roles = await _list_level_roles(client, GUILD_ID)
    assert [r for r in roles if r.level == 8] == [updated]


async def test_list_level_roles_sorted_by_level(client: AsyncTestClient[Litestar]) -> None:
    await _set_level_role(client, GUILD_ID, 9, 9001)
    await _set_level_role(client, GUILD_ID, 4, 9002)
    await _set_level_role(client, GUILD_ID, 7, 9003)
    roles = await _list_level_roles(client, GUILD_ID)
    assert [r.level for r in roles] == sorted(r.level for r in roles)


async def test_delete_level_role_removes_it(client: AsyncTestClient[Litestar]) -> None:
    await _set_level_role(client, GUILD_ID, 11, 11001)
    delete_response = await client.delete(f"/api/guilds/{GUILD_ID}/level-roles/11")
    assert delete_response.status_code == 204
    roles = await _list_level_roles(client, GUILD_ID)
    assert all(r.level != 11 for r in roles)


async def test_delete_missing_level_role_404s(client: AsyncTestClient[Litestar]) -> None:
    response = await client.delete(f"/api/guilds/{GUILD_ID}/level-roles/999")
    assert response.status_code == 404


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
