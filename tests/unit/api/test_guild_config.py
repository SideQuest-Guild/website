from typing import TYPE_CHECKING, Any

from sidequest_common.models.guild import DEFAULT_LEVEL_UP_MESSAGE
from sidequest_common.schemas import GuildConfigUpdate
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient


async def _get_guild_config(client: AsyncTestClient[Litestar], guild_id: int) -> dict:
    response = await client.get(f"/api/guilds/{guild_id}/config")
    assert response.status_code == 200
    return response.json()


async def _update_guild_config(client: AsyncTestClient[Litestar], guild_id: int, **changes: Any) -> dict:
    body = GuildConfigUpdate(**changes).model_dump(mode="json", exclude_unset=True)
    response = await client.patch(f"/api/guilds/{guild_id}/config", json=body)
    assert response.status_code == 200
    return response.json()


async def test_requests_without_api_key_are_rejected(client: AsyncTestClient[Litestar]) -> None:
    response = await client.get(f"/api/guilds/{GUILD_ID}/config", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


async def test_health_needs_no_key(client: AsyncTestClient[Litestar]) -> None:
    client.headers.pop("X-API-Key")
    assert (await client.get("/health")).json() == {"status": "ok", "database": "ok"}


async def test_config_created_with_defaults_once(client: AsyncTestClient[Litestar]) -> None:
    first = await _get_guild_config(client, GUILD_ID)
    second = await _get_guild_config(client, GUILD_ID)
    assert first == second
    assert first["level_up_message"] == DEFAULT_LEVEL_UP_MESSAGE
    assert (first["xp_min"], first["xp_max"], first["xp_cooldown_seconds"]) == (15, 25, 60)


async def test_partial_update_only_touches_sent_fields(client: AsyncTestClient[Litestar]) -> None:
    await _update_guild_config(client, GUILD_ID, log_channel_id=42, no_xp_channel_ids=[7])
    updated = await _update_guild_config(client, GUILD_ID, xp_max=40)
    assert (updated["log_channel_id"], updated["no_xp_channel_ids"], updated["xp_max"]) == (42, [7], 40)


async def test_explicit_null_clears_optional_channel(client: AsyncTestClient[Litestar]) -> None:
    await _update_guild_config(client, GUILD_ID, log_channel_id=42)
    cleared = await _update_guild_config(client, GUILD_ID, log_channel_id=None)
    assert cleared["log_channel_id"] is None


async def test_link_role_ids_round_trip_and_clear(client: AsyncTestClient[Litestar]) -> None:
    updated = await _update_guild_config(client, GUILD_ID, linked_role_id=111, battlenet_role_id=222)
    assert (updated["linked_role_id"], updated["battlenet_role_id"]) == (111, 222)
    cleared = await _update_guild_config(client, GUILD_ID, linked_role_id=None)
    assert cleared["linked_role_id"] is None
    assert cleared["battlenet_role_id"] == 222


async def test_gate_role_id_round_trips_and_clears(client: AsyncTestClient[Litestar]) -> None:
    updated = await _update_guild_config(client, GUILD_ID, gate_role_id=333)
    assert updated["gate_role_id"] == 333
    cleared = await _update_guild_config(client, GUILD_ID, gate_role_id=None)
    assert cleared["gate_role_id"] is None


async def test_xp_min_above_stored_max_rejected(client: AsyncTestClient[Litestar]) -> None:
    body = GuildConfigUpdate(xp_min=30).model_dump(mode="json", exclude_unset=True)
    response = await client.patch(f"/api/guilds/{GUILD_ID}/config", json=body)
    assert response.status_code == 400
    assert (await _get_guild_config(client, GUILD_ID))["xp_min"] == 15
