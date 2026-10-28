from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient

from sidequest_api.app import create_app
from sidequest_common.settings import APISettings, DatabaseSettings
from tests.conftest import GUILD_ID, TEST_API_KEY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from litestar import Litestar


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    site = tmp_path / "dist"
    (site / "events").mkdir(parents=True)
    (site / "index.html").write_text("<h1>home</h1>")
    (site / "events" / "index.html").write_text("<h1>events</h1>")
    (site / "404.html").write_text("<h1>lost</h1>")
    return site


@pytest.fixture
async def site_client(database_url: str, dist: Path) -> AsyncIterator[AsyncTestClient[Litestar]]:
    app = create_app(DatabaseSettings(URL=database_url), APISettings(KEY=TEST_API_KEY), website_dist=dist)
    async with AsyncTestClient(app=app) as client:
        yield client


async def test_built_site_served_at_root_with_directory_pages(site_client: AsyncTestClient[Litestar]) -> None:
    assert (await site_client.get("/")).text == "<h1>home</h1>"
    assert (await site_client.get("/events/")).text == "<h1>events</h1>"


async def test_unknown_site_path_gets_the_site_404_page(site_client: AsyncTestClient[Litestar]) -> None:
    response = await site_client.get("/no-such-page")
    assert response.status_code == 404
    assert response.text == "<h1>lost</h1>"


async def test_site_at_root_does_not_shadow_backend_routes(site_client: AsyncTestClient[Litestar]) -> None:
    assert (await site_client.get("/health")).json()["status"] == "ok"
    assert (await site_client.get("/schema/openapi.json")).status_code == 200
    assert (await site_client.get(f"/api/guilds/{GUILD_ID}/config")).status_code == 401
    authed = await site_client.get(f"/api/guilds/{GUILD_ID}/config", headers={"X-API-Key": TEST_API_KEY})
    assert authed.json()["guild_id"] == GUILD_ID


async def test_placeholder_home_until_site_is_built(database_url: str, tmp_path: Path) -> None:
    app = create_app(DatabaseSettings(URL=database_url), APISettings(KEY=TEST_API_KEY), website_dist=tmp_path / "x")
    async with AsyncTestClient(app=app) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "SideQuest" in response.text
