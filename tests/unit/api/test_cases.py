from typing import TYPE_CHECKING

import pytest

from sidequest_bot.api_client import NotFoundError
from sidequest_common.schemas import CaseAction, ModCaseCreate, ModCaseUpdate
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from sidequest_bot.api_client import SideQuestAPI

OTHER_GUILD_ID = GUILD_ID + 1


def _case(action: CaseAction = CaseAction.WARN, user_id: int = 100, reason: str | None = "spamming") -> ModCaseCreate:
    return ModCaseCreate(action=action, user_id=user_id, moderator_id=999, reason=reason)


async def test_case_numbers_start_at_one_and_increment_per_guild(api: SideQuestAPI) -> None:
    first = await api.create_case(GUILD_ID, _case())
    second = await api.create_case(GUILD_ID, _case())
    assert (first.case_number, second.case_number) == (1, 2)


async def test_case_numbering_is_independent_per_guild(api: SideQuestAPI) -> None:
    await api.create_case(GUILD_ID, _case())
    await api.create_case(GUILD_ID, _case())
    other_first = await api.create_case(OTHER_GUILD_ID, _case())
    assert other_first.case_number == 1


async def test_list_cases_is_newest_first(api: SideQuestAPI) -> None:
    first = await api.create_case(GUILD_ID, _case())
    second = await api.create_case(GUILD_ID, _case())
    third = await api.create_case(GUILD_ID, _case())
    cases = await api.list_cases(GUILD_ID)
    assert [case.case_number for case in cases] == [third.case_number, second.case_number, first.case_number]


async def test_list_cases_filters_by_user(api: SideQuestAPI) -> None:
    await api.create_case(GUILD_ID, _case(user_id=100))
    target = await api.create_case(GUILD_ID, _case(user_id=200))
    await api.create_case(GUILD_ID, _case(user_id=100))
    cases = await api.list_cases(GUILD_ID, user_id=200)
    assert [case.case_number for case in cases] == [target.case_number]


async def test_list_cases_paginates(api: SideQuestAPI) -> None:
    for _ in range(5):
        await api.create_case(GUILD_ID, _case())
    page1 = await api.list_cases(GUILD_ID, limit=2, offset=0)
    page2 = await api.list_cases(GUILD_ID, limit=2, offset=2)
    assert [case.case_number for case in page1] == [5, 4]
    assert [case.case_number for case in page2] == [3, 2]


async def test_get_missing_case_is_404(api: SideQuestAPI) -> None:
    with pytest.raises(NotFoundError):
        await api.get_case(GUILD_ID, 1)


async def test_get_case_returns_recorded_case(api: SideQuestAPI) -> None:
    created = await api.create_case(GUILD_ID, _case(action=CaseAction.BAN, reason="raid"))
    fetched = await api.get_case(GUILD_ID, created.case_number)
    assert (fetched.action, fetched.reason, fetched.user_id) == (CaseAction.BAN, "raid", 100)


async def test_update_case_changes_reason_only(api: SideQuestAPI) -> None:
    created = await api.create_case(GUILD_ID, _case(reason="initial"))
    updated = await api.update_case(GUILD_ID, created.case_number, ModCaseUpdate(reason="corrected"))
    assert updated.reason == "corrected"
    assert updated.case_number == created.case_number
    assert updated.action == created.action


async def test_update_missing_case_is_404(api: SideQuestAPI) -> None:
    with pytest.raises(NotFoundError):
        await api.update_case(GUILD_ID, 1, ModCaseUpdate(reason="nope"))
