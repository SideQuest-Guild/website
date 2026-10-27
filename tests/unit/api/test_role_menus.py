from typing import TYPE_CHECKING

import pytest

from sidequest_bot.api_client import APIError, NotFoundError
from sidequest_common.schemas import RoleMenuCreate, RoleMenuOptionUpsert, RoleMenuSchema, RoleMenuUpdate
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from sidequest_bot.api_client import SideQuestAPI

OTHER_GUILD_ID = 1900000000000000000


async def _create_menu(api: SideQuestAPI, guild_id: int = GUILD_ID, **overrides: object) -> RoleMenuSchema:
    payload = {"channel_id": 111, "title": "Pick your roles", **overrides}
    return await api.create_role_menu(guild_id, RoleMenuCreate.model_validate(payload))


async def test_create_and_get_round_trips(api: SideQuestAPI) -> None:
    created = await _create_menu(api, description="Pick a vibe", max_roles=2)
    fetched = await api.get_role_menu(GUILD_ID, created.id)
    assert fetched == created
    assert fetched.guild_id == GUILD_ID
    assert fetched.channel_id == 111
    assert fetched.description == "Pick a vibe"
    assert fetched.max_roles == 2
    assert fetched.options == []
    assert fetched.message_id is None


async def test_list_menus_returns_only_this_guild(api: SideQuestAPI) -> None:
    mine = await _create_menu(api)
    await _create_menu(api, guild_id=OTHER_GUILD_ID)
    menus = await api.list_role_menus(GUILD_ID)
    assert [menu.id for menu in menus] == [mine.id]


async def test_update_only_touches_sent_fields(api: SideQuestAPI) -> None:
    created = await _create_menu(api, description="original")
    updated = await api.update_role_menu(GUILD_ID, created.id, RoleMenuUpdate(title="New title"))
    assert updated.title == "New title"
    assert updated.description == "original"


async def test_update_can_clear_optional_description(api: SideQuestAPI) -> None:
    created = await _create_menu(api, description="original")
    updated = await api.update_role_menu(GUILD_ID, created.id, RoleMenuUpdate(description=None))
    assert updated.description is None


async def test_delete_menu_removes_it(api: SideQuestAPI) -> None:
    created = await _create_menu(api)
    await api.delete_role_menu(GUILD_ID, created.id)
    with pytest.raises(NotFoundError):
        await api.get_role_menu(GUILD_ID, created.id)


async def test_cross_guild_menu_access_is_404(api: SideQuestAPI) -> None:
    created = await _create_menu(api, guild_id=OTHER_GUILD_ID)
    with pytest.raises(NotFoundError):
        await api.get_role_menu(GUILD_ID, created.id)
    with pytest.raises(NotFoundError):
        await api.update_role_menu(GUILD_ID, created.id, RoleMenuUpdate(title="nope"))
    with pytest.raises(NotFoundError):
        await api.delete_role_menu(GUILD_ID, created.id)
    with pytest.raises(NotFoundError):
        await api.upsert_role_menu_option(GUILD_ID, created.id, 1, RoleMenuOptionUpsert(label="x"))
    with pytest.raises(NotFoundError):
        await api.delete_role_menu_option(GUILD_ID, created.id, 1)


async def test_adding_options_appends_in_order(api: SideQuestAPI) -> None:
    created = await _create_menu(api)
    for i, role_id in enumerate((101, 102, 103)):
        menu = await api.upsert_role_menu_option(GUILD_ID, created.id, role_id, RoleMenuOptionUpsert(label=f"Role {i}"))
    assert [opt.role_id for opt in menu.options] == [101, 102, 103]
    assert [opt.position for opt in menu.options] == [0, 1, 2]


async def test_editing_existing_option_does_not_duplicate(api: SideQuestAPI) -> None:
    created = await _create_menu(api)
    await api.upsert_role_menu_option(GUILD_ID, created.id, 101, RoleMenuOptionUpsert(label="A"))
    menu = await api.upsert_role_menu_option(
        GUILD_ID, created.id, 101, RoleMenuOptionUpsert(label="A-edited", description="changed")
    )
    assert len(menu.options) == 1
    assert menu.options[0].label == "A-edited"
    assert menu.options[0].description == "changed"


async def test_inserting_at_explicit_position_shifts_others(api: SideQuestAPI) -> None:
    created = await _create_menu(api)
    await api.upsert_role_menu_option(GUILD_ID, created.id, 101, RoleMenuOptionUpsert(label="A"))
    await api.upsert_role_menu_option(GUILD_ID, created.id, 102, RoleMenuOptionUpsert(label="B"))
    menu = await api.upsert_role_menu_option(GUILD_ID, created.id, 103, RoleMenuOptionUpsert(label="C", position=0))
    assert [opt.role_id for opt in menu.options] == [103, 101, 102]
    assert [opt.position for opt in menu.options] == [0, 1, 2]


async def test_moving_existing_option_to_a_new_position_has_no_duplicate_positions(api: SideQuestAPI) -> None:
    created = await _create_menu(api)
    await api.upsert_role_menu_option(GUILD_ID, created.id, 101, RoleMenuOptionUpsert(label="A"))
    await api.upsert_role_menu_option(GUILD_ID, created.id, 102, RoleMenuOptionUpsert(label="B"))
    await api.upsert_role_menu_option(GUILD_ID, created.id, 103, RoleMenuOptionUpsert(label="C"))
    menu = await api.upsert_role_menu_option(GUILD_ID, created.id, 101, RoleMenuOptionUpsert(label="A", position=2))
    positions = [opt.position for opt in menu.options]
    assert positions == sorted(positions)
    assert positions == list(range(len(positions)))
    assert [opt.role_id for opt in menu.options] == [102, 103, 101]


async def test_max_25_options_rejected(api: SideQuestAPI) -> None:
    created = await _create_menu(api)
    for role_id in range(1, 26):
        await api.upsert_role_menu_option(GUILD_ID, created.id, role_id, RoleMenuOptionUpsert(label=f"R{role_id}"))
    with pytest.raises(APIError) as excinfo:
        await api.upsert_role_menu_option(GUILD_ID, created.id, 999, RoleMenuOptionUpsert(label="overflow"))
    assert excinfo.value.status_code == 400
    menu = await api.get_role_menu(GUILD_ID, created.id)
    assert len(menu.options) == 25


async def test_deleting_option_repacks_positions(api: SideQuestAPI) -> None:
    created = await _create_menu(api)
    for role_id in (101, 102, 103):
        await api.upsert_role_menu_option(GUILD_ID, created.id, role_id, RoleMenuOptionUpsert(label=f"R{role_id}"))
    menu = await api.delete_role_menu_option(GUILD_ID, created.id, 102)
    assert [opt.role_id for opt in menu.options] == [101, 103]
    assert [opt.position for opt in menu.options] == [0, 1]


async def test_deleting_missing_option_is_404(api: SideQuestAPI) -> None:
    created = await _create_menu(api)
    with pytest.raises(NotFoundError):
        await api.delete_role_menu_option(GUILD_ID, created.id, 999)
