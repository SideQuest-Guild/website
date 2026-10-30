from typing import TYPE_CHECKING

from sidequest_common.schemas import CaseAction, ModCaseSchema, ModCaseUpdate
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient

OTHER_GUILD_ID = GUILD_ID + 1


def _case(action: CaseAction = CaseAction.WARN, user_id: int = 100, reason: str | None = "spamming") -> dict:
    return {"action": action.value, "user_id": user_id, "moderator_id": 999, "reason": reason}


async def _create_case(client: AsyncTestClient[Litestar], guild_id: int, **overrides: object) -> ModCaseSchema:
    payload = {**_case(), **overrides}
    response = await client.post(f"/api/guilds/{guild_id}/cases", json=payload)
    assert response.status_code == 201
    return ModCaseSchema.model_validate(response.json())


async def _list_cases(
    client: AsyncTestClient[Litestar], guild_id: int, *, user_id: int | None = None, limit: int = 25, offset: int = 0
) -> list[ModCaseSchema]:
    params: dict[str, int] = {"limit": limit, "offset": offset}
    if user_id is not None:
        params["user_id"] = user_id
    response = await client.get(f"/api/guilds/{guild_id}/cases", params=params)
    assert response.status_code == 200
    return [ModCaseSchema.model_validate(case) for case in response.json()]


async def test_case_numbers_start_at_one_and_increment_per_guild(client: AsyncTestClient[Litestar]) -> None:
    first = await _create_case(client, GUILD_ID)
    second = await _create_case(client, GUILD_ID)
    assert (first.case_number, second.case_number) == (1, 2)


async def test_case_numbering_is_independent_per_guild(client: AsyncTestClient[Litestar]) -> None:
    await _create_case(client, GUILD_ID)
    await _create_case(client, GUILD_ID)
    other_first = await _create_case(client, OTHER_GUILD_ID)
    assert other_first.case_number == 1


async def test_list_cases_is_newest_first(client: AsyncTestClient[Litestar]) -> None:
    first = await _create_case(client, GUILD_ID)
    second = await _create_case(client, GUILD_ID)
    third = await _create_case(client, GUILD_ID)
    cases = await _list_cases(client, GUILD_ID)
    assert [case.case_number for case in cases] == [third.case_number, second.case_number, first.case_number]


async def test_list_cases_filters_by_user(client: AsyncTestClient[Litestar]) -> None:
    await _create_case(client, GUILD_ID, user_id=100)
    target = await _create_case(client, GUILD_ID, user_id=200)
    await _create_case(client, GUILD_ID, user_id=100)
    cases = await _list_cases(client, GUILD_ID, user_id=200)
    assert [case.case_number for case in cases] == [target.case_number]


async def test_list_cases_paginates(client: AsyncTestClient[Litestar]) -> None:
    for _ in range(5):
        await _create_case(client, GUILD_ID)
    page1 = await _list_cases(client, GUILD_ID, limit=2, offset=0)
    page2 = await _list_cases(client, GUILD_ID, limit=2, offset=2)
    assert [case.case_number for case in page1] == [5, 4]
    assert [case.case_number for case in page2] == [3, 2]


async def test_get_missing_case_is_404(client: AsyncTestClient[Litestar]) -> None:
    response = await client.get(f"/api/guilds/{GUILD_ID}/cases/1")
    assert response.status_code == 404


async def test_get_case_returns_recorded_case(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_case(client, GUILD_ID, action=CaseAction.BAN.value, reason="raid")
    response = await client.get(f"/api/guilds/{GUILD_ID}/cases/{created.case_number}")
    assert response.status_code == 200
    fetched = ModCaseSchema.model_validate(response.json())
    assert (fetched.action, fetched.reason, fetched.user_id) == (CaseAction.BAN, "raid", 100)


async def test_update_case_changes_reason_only(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_case(client, GUILD_ID, reason="initial")
    body = ModCaseUpdate(reason="corrected").model_dump(mode="json", exclude_unset=True)
    response = await client.patch(f"/api/guilds/{GUILD_ID}/cases/{created.case_number}", json=body)
    assert response.status_code == 200
    updated = ModCaseSchema.model_validate(response.json())
    assert updated.reason == "corrected"
    assert updated.case_number == created.case_number
    assert updated.action == created.action


async def test_update_missing_case_is_404(client: AsyncTestClient[Litestar]) -> None:
    body = ModCaseUpdate(reason="nope").model_dump(mode="json", exclude_unset=True)
    response = await client.patch(f"/api/guilds/{GUILD_ID}/cases/1", json=body)
    assert response.status_code == 404
