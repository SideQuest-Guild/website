from typing import TYPE_CHECKING

from tests.unit.api.conftest import login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient

PATH = "/api/discord/online"


async def test_signed_out_is_401(member_client: AsyncTestClient) -> None:
    response = await member_client.get(PATH)
    assert response.status_code == 401


async def test_signed_in_non_member_is_403(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6001, is_guild_member=False)
    response = await member_client.get(PATH)
    assert response.status_code == 403


async def test_widget_is_trimmed_to_name_status_avatar_activity(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=6002)
    discord_state["widget"] = {
        "id": "1564671275316543508",
        "name": "SideQuest",
        "instant_invite": "https://discord.gg/nwncP7H9Hh",
        "presence_count": 2,
        "channels": [],
        "members": [
            {
                "id": "0",
                "username": "Oakenshield",
                "discriminator": "0000",
                "avatar": None,
                "status": "online",
                "avatar_url": "https://cdn.discordapp.com/widget-avatars/aaa/bbb",
                "activity": {"name": "World of Warcraft: Forever"},
            },
            {
                "id": "1",
                "username": "Lantern",
                "discriminator": "0000",
                "avatar": None,
                "status": "idle",
                "avatar_url": "https://cdn.discordapp.com/widget-avatars/ccc/ddd",
                "game": {"name": "Deadlock"},
            },
        ],
    }
    response = await member_client.get(PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["presence_count"] == 2
    assert body["members"] == [
        {
            "name": "Oakenshield",
            "status": "online",
            "avatar_url": "https://cdn.discordapp.com/widget-avatars/aaa/bbb",
            "activity": "World of Warcraft: Forever",
        },
        {
            "name": "Lantern",
            "status": "idle",
            "avatar_url": "https://cdn.discordapp.com/widget-avatars/ccc/ddd",
            "activity": "Deadlock",
        },
    ]


async def test_members_are_sorted_online_then_idle_then_dnd_then_name(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=6003)

    def member(name: str, status: str) -> dict:
        return {"username": name, "status": status, "avatar_url": None}

    discord_state["widget"] = {
        "presence_count": 4,
        "members": [
            member("Zed", "online"),
            member("Mira", "dnd"),
            member("Aria", "idle"),
            member("Beren", "online"),
        ],
    }
    response = await member_client.get(PATH)
    names = [m["name"] for m in response.json()["members"]]
    assert names == ["Beren", "Zed", "Aria", "Mira"]


async def test_second_request_within_ttl_is_served_from_cache(
    member_client: AsyncTestClient, discord_state: dict
) -> None:
    await login_as(member_client, discord_state, discord_id=6004)
    discord_state["widget"] = {"presence_count": 1, "members": [{"username": "A", "status": "online"}]}
    first = await member_client.get(PATH)
    assert first.json()["presence_count"] == 1
    assert discord_state["widget_calls"] == 1

    # Discord's answer changes, but the cached result (~60s TTL) should still be served without a new fetch.
    discord_state["widget"] = {"presence_count": 99, "members": []}
    second = await member_client.get(PATH)
    assert second.json()["presence_count"] == 1
    assert discord_state["widget_calls"] == 1


async def test_discord_failure_returns_empty_list_not_500(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6005)
    discord_state["widget_down"] = True
    response = await member_client.get(PATH)
    assert response.status_code == 200
    body = response.json()
    assert body == {"presence_count": None, "members": [], "ok": False}


async def test_response_is_never_edge_cached(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=6006)
    response = await member_client.get(PATH)
    assert "cloudflare-cdn-cache-control" not in {k.lower() for k in response.headers}
