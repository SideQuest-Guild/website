from typing import TYPE_CHECKING

from tests.unit.api.conftest import OFFICER_ROLE_ID, login_as

if TYPE_CHECKING:
    from litestar.testing import AsyncTestClient


async def test_addon_with_http_download_url_is_rejected(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=3001, roles=[OFFICER_ROLE_ID])
    response = await member_client.post(
        "/api/addons",
        json={
            "slug": "deadly-boss-mods",
            "name": "Deadly Boss Mods",
            "summary": "Raid warnings",
            "version": "1.0.0",
            "download_url": "http://example.com/dbm.zip",
            "homepage_url": None,
        },
    )
    assert response.status_code == 400


async def test_addon_create_requires_officer(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=3002, roles=[])
    response = await member_client.post(
        "/api/addons",
        json={
            "slug": "deadly-boss-mods",
            "name": "Deadly Boss Mods",
            "summary": "Raid warnings",
            "version": "1.0.0",
            "download_url": "https://example.com/dbm.zip",
            "homepage_url": None,
        },
    )
    assert response.status_code == 403


async def test_officer_can_create_and_list_addon(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=3003, roles=[OFFICER_ROLE_ID])
    create_response = await member_client.post(
        "/api/addons",
        json={
            "slug": "deadly-boss-mods",
            "name": "Deadly Boss Mods",
            "summary": "Raid warnings",
            "version": "1.0.0",
            "download_url": "https://example.com/dbm.zip",
            "homepage_url": "https://example.com",
        },
    )
    assert create_response.status_code == 201

    list_response = await member_client.get("/api/addons")
    assert list_response.status_code == 200
    assert [addon["slug"] for addon in list_response.json()] == ["deadly-boss-mods"]


async def test_duplicate_slug_is_409(member_client: AsyncTestClient, discord_state: dict) -> None:
    await login_as(member_client, discord_state, discord_id=3004, roles=[OFFICER_ROLE_ID])
    body = {
        "slug": "weakauras",
        "name": "WeakAuras",
        "summary": "Custom alerts",
        "version": "2.0.0",
        "download_url": "https://example.com/wa.zip",
        "homepage_url": None,
    }
    first = await member_client.post("/api/addons", json=body)
    assert first.status_code == 201
    second = await member_client.post("/api/addons", json=body)
    assert second.status_code == 409
