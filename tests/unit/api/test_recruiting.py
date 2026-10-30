from typing import TYPE_CHECKING

from sqlalchemy import select

from sidequest_common.models import OfficerAudit
from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PATH = "/api/recruiting"


async def test_public_get_with_nothing_set_returns_empty_lists(client: AsyncTestClient) -> None:
    response = await client.get(PATH)
    assert response.status_code == 200
    body = response.json()
    assert body == {"roles": [], "classes": [], "updated_at": None}


async def test_update_requires_officer(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=5001, roles=[])
    response = await member_client.put(PATH, json={"roles": [], "classes": []})
    assert response.status_code == 403


async def test_update_requires_sign_in(member_client: AsyncTestClient) -> None:
    response = await member_client.put(PATH, json={"roles": [], "classes": []})
    assert response.status_code == 401


async def test_officer_can_replace_needs_and_public_get_reflects_it(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=5002, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(
        PATH,
        json={
            "roles": [{"role": "tank", "priority": "high", "note": "semi-core"}],
            "classes": [{"class": "druid", "priority": "normal", "note": None}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["roles"] == [{"role": "tank", "priority": "high", "note": "semi-core"}]
    assert body["classes"] == [{"class": "druid", "priority": "normal", "note": None}]
    assert body["updated_at"] is not None

    public = await member_client.get(PATH)
    assert public.json()["roles"] == [{"role": "tank", "priority": "high", "note": "semi-core"}]


async def test_update_replaces_rather_than_merges(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=5003, roles=[OFFICER_ROLE_ID])
    await member_client.put(PATH, json={"roles": [{"role": "tank"}], "classes": [{"class": "druid"}]})
    response = await member_client.put(PATH, json={"roles": [{"role": "healer"}], "classes": []})
    assert response.status_code == 200
    body = response.json()
    assert [want["role"] for want in body["roles"]] == ["healer"]
    assert body["classes"] == []


async def test_duplicate_role_is_rejected(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=5004, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(PATH, json={"roles": [{"role": "tank"}, {"role": "tank"}], "classes": []})
    assert response.status_code == 400


async def test_duplicate_class_is_rejected(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=5005, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(PATH, json={"roles": [], "classes": [{"class": "druid"}, {"class": "druid"}]})
    assert response.status_code == 400


async def test_note_over_140_chars_is_rejected(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=5006, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(PATH, json={"roles": [{"role": "tank", "note": "x" * 141}], "classes": []})
    assert response.status_code == 400


async def test_invalid_priority_is_rejected(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=5007, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(PATH, json={"roles": [{"role": "tank", "priority": "urgent"}], "classes": []})
    assert response.status_code == 400


async def test_update_records_officer_audit(
    member_client: AsyncTestClient, discord_state: dict, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await login_as(member_client, discord_state, discord_id=5008, roles=[OFFICER_ROLE_ID])
    response = await member_client.put(PATH, json={"roles": [{"role": "dps"}], "classes": []})
    assert response.status_code == 200
    async with db_sessionmaker() as session:
        rows = (await session.execute(select(OfficerAudit))).scalars().all()
        assert len(rows) == 1
        assert rows[0].action == "recruiting.update"
        assert rows[0].subject_type == "recruiting"
