from typing import TYPE_CHECKING

from sidequest_common.schemas import RoleMenuOptionUpsert, RoleMenuSchema, RoleMenuUpdate
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient

OTHER_GUILD_ID = 1900000000000000000


async def _create_menu(
    client: AsyncTestClient[Litestar], guild_id: int = GUILD_ID, **overrides: object
) -> RoleMenuSchema:
    payload = {"channel_id": 111, "title": "Pick your roles", **overrides}
    response = await client.post(f"/api/guilds/{guild_id}/role-menus", json=payload)
    assert response.status_code == 201
    return RoleMenuSchema.model_validate(response.json())


async def test_create_and_get_round_trips(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client, description="Pick a vibe", max_roles=2)
    fetched_response = await client.get(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}")
    assert fetched_response.status_code == 200
    fetched = RoleMenuSchema.model_validate(fetched_response.json())
    assert fetched == created
    assert fetched.guild_id == GUILD_ID
    assert fetched.channel_id == 111
    assert fetched.description == "Pick a vibe"
    assert fetched.max_roles == 2
    assert fetched.options == []
    assert fetched.message_id is None


async def test_list_menus_returns_only_this_guild(client: AsyncTestClient[Litestar]) -> None:
    mine = await _create_menu(client)
    await _create_menu(client, guild_id=OTHER_GUILD_ID)
    response = await client.get(f"/api/guilds/{GUILD_ID}/role-menus")
    assert response.status_code == 200
    menus = [RoleMenuSchema.model_validate(menu) for menu in response.json()]
    assert [menu.id for menu in menus] == [mine.id]


async def test_update_only_touches_sent_fields(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client, description="original")
    body = RoleMenuUpdate(title="New title").model_dump(mode="json", exclude_unset=True)
    response = await client.patch(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}", json=body)
    assert response.status_code == 200
    updated = RoleMenuSchema.model_validate(response.json())
    assert updated.title == "New title"
    assert updated.description == "original"


async def test_update_can_clear_optional_description(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client, description="original")
    body = RoleMenuUpdate(description=None).model_dump(mode="json", exclude_unset=True)
    response = await client.patch(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}", json=body)
    assert response.status_code == 200
    updated = RoleMenuSchema.model_validate(response.json())
    assert updated.description is None


async def test_delete_menu_removes_it(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client)
    delete_response = await client.delete(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}")
    assert delete_response.status_code == 204
    response = await client.get(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}")
    assert response.status_code == 404


async def test_cross_guild_menu_access_is_404(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client, guild_id=OTHER_GUILD_ID)
    assert (await client.get(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}")).status_code == 404
    update_body = RoleMenuUpdate(title="nope").model_dump(mode="json", exclude_unset=True)
    assert (await client.patch(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}", json=update_body)).status_code == 404
    assert (await client.delete(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}")).status_code == 404
    option_body = RoleMenuOptionUpsert(label="x").model_dump(mode="json")
    assert (
        await client.put(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/1", json=option_body)
    ).status_code == 404
    assert (await client.delete(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/1")).status_code == 404


async def test_adding_options_appends_in_order(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client)
    menu = created
    for i, role_id in enumerate((101, 102, 103)):
        body = RoleMenuOptionUpsert(label=f"Role {i}").model_dump(mode="json")
        response = await client.put(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/{role_id}", json=body)
        assert response.status_code == 200
        menu = RoleMenuSchema.model_validate(response.json())
    assert [opt.role_id for opt in menu.options] == [101, 102, 103]
    assert [opt.position for opt in menu.options] == [0, 1, 2]


async def test_editing_existing_option_does_not_duplicate(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client)
    await client.put(
        f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/101",
        json=RoleMenuOptionUpsert(label="A").model_dump(mode="json"),
    )
    response = await client.put(
        f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/101",
        json=RoleMenuOptionUpsert(label="A-edited", description="changed").model_dump(mode="json"),
    )
    assert response.status_code == 200
    menu = RoleMenuSchema.model_validate(response.json())
    assert len(menu.options) == 1
    assert menu.options[0].label == "A-edited"
    assert menu.options[0].description == "changed"


async def test_inserting_at_explicit_position_shifts_others(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client)
    await client.put(
        f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/101",
        json=RoleMenuOptionUpsert(label="A").model_dump(mode="json"),
    )
    await client.put(
        f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/102",
        json=RoleMenuOptionUpsert(label="B").model_dump(mode="json"),
    )
    response = await client.put(
        f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/103",
        json=RoleMenuOptionUpsert(label="C", position=0).model_dump(mode="json"),
    )
    assert response.status_code == 200
    menu = RoleMenuSchema.model_validate(response.json())
    assert [opt.role_id for opt in menu.options] == [103, 101, 102]
    assert [opt.position for opt in menu.options] == [0, 1, 2]


async def test_moving_existing_option_to_a_new_position_has_no_duplicate_positions(
    client: AsyncTestClient[Litestar],
) -> None:
    created = await _create_menu(client)
    for role_id, label in ((101, "A"), (102, "B"), (103, "C")):
        await client.put(
            f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/{role_id}",
            json=RoleMenuOptionUpsert(label=label).model_dump(mode="json"),
        )
    response = await client.put(
        f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/101",
        json=RoleMenuOptionUpsert(label="A", position=2).model_dump(mode="json"),
    )
    assert response.status_code == 200
    menu = RoleMenuSchema.model_validate(response.json())
    positions = [opt.position for opt in menu.options]
    assert positions == sorted(positions)
    assert positions == list(range(len(positions)))
    assert [opt.role_id for opt in menu.options] == [102, 103, 101]


async def test_max_25_options_rejected(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client)
    for role_id in range(1, 26):
        response = await client.put(
            f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/{role_id}",
            json=RoleMenuOptionUpsert(label=f"R{role_id}").model_dump(mode="json"),
        )
        assert response.status_code == 200
    overflow = await client.put(
        f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/999",
        json=RoleMenuOptionUpsert(label="overflow").model_dump(mode="json"),
    )
    assert overflow.status_code == 400
    fetched = await client.get(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}")
    menu = RoleMenuSchema.model_validate(fetched.json())
    assert len(menu.options) == 25


async def test_deleting_option_repacks_positions(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client)
    for role_id in (101, 102, 103):
        await client.put(
            f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/{role_id}",
            json=RoleMenuOptionUpsert(label=f"R{role_id}").model_dump(mode="json"),
        )
    response = await client.delete(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/102")
    assert response.status_code == 200
    menu = RoleMenuSchema.model_validate(response.json())
    assert [opt.role_id for opt in menu.options] == [101, 103]
    assert [opt.position for opt in menu.options] == [0, 1]


async def test_deleting_missing_option_is_404(client: AsyncTestClient[Litestar]) -> None:
    created = await _create_menu(client)
    response = await client.delete(f"/api/guilds/{GUILD_ID}/role-menus/{created.id}/options/999")
    assert response.status_code == 404
