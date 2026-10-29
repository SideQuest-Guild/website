from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient

from sidequest_api.app import create_app
from sidequest_api.lib.website import EDGE_CACHE_HEADER
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import GUILD_ID, TEST_API_KEY
from tests.unit.api.conftest import _discord_transport, login_as

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
    (site / "_astro").mkdir()
    (site / "_astro" / "room.AbC123.webp").write_bytes(b"webp")
    return site


@pytest.fixture
async def site_client(database_url: str, dist: Path) -> AsyncIterator[AsyncTestClient[Litestar]]:
    app = create_app(DatabaseSettings(URL=database_url), APISettings(KEY=TEST_API_KEY), website_dist=dist)
    async with AsyncTestClient(app=app) as client:
        yield client


@pytest.fixture
async def member_site_client(
    database_url: str, member_web_settings: WebSettings, discord_state: dict, dist: Path
) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """The built site plus Discord sign-in, cookies persisted like a browser."""
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        member_web_settings,
        discord_transport=_discord_transport(discord_state),
        website_dist=dist,
    )
    async with AsyncTestClient(app=app) as client:
        yield client


async def test_built_site_served_at_root_with_directory_pages(site_client: AsyncTestClient[Litestar]) -> None:
    assert (await site_client.get("/")).text == "<h1>home</h1>"
    assert (await site_client.get("/events/")).text == "<h1>events</h1>"


async def test_unknown_site_path_gets_the_site_404_page(site_client: AsyncTestClient[Litestar]) -> None:
    response = await site_client.get("/no-such-page")
    assert response.status_code == 404
    assert response.text == "<h1>lost</h1>"


async def test_hashed_assets_cache_for_good_and_pages_revalidate(site_client: AsyncTestClient[Litestar]) -> None:
    """A deploy must show at once (browsers revalidate pages) while hashed assets never refetch."""
    asset = await site_client.get("/_astro/room.AbC123.webp")
    assert asset.content == b"webp"
    assert set(asset.headers["cache-control"].split(", ")) == {"public", "max-age=31536000", "immutable"}
    for path in ("/", "/events/"):
        page = await site_client.get(path)
        assert page.headers["cache-control"] == "no-cache"
        assert page.headers[EDGE_CACHE_HEADER].startswith("max-age=60,")
    assert (await site_client.get("/_astro/missing.webp")).status_code == 404


SHARED_PATHS = ("/", "/events/", "/no-such-page", "/_astro/room.AbC123.webp", "/api/discord/live")


async def test_shared_responses_never_carry_a_session_cookie(
    member_site_client: AsyncTestClient[Litestar], discord_state: dict
) -> None:
    """Cloudflare keeps one copy of these for everyone, so none may set (or clear) anyone's session."""
    await login_as(member_site_client, discord_state, discord_id=4242)
    for path in SHARED_PATHS:
        assert "set-cookie" not in (await member_site_client.get(path)).headers, path
    assert (await member_site_client.get("/api/me")).status_code == 200

    member_site_client.cookies.set("sq_session", "not-a-real-session")
    for path in SHARED_PATHS:
        assert "set-cookie" not in (await member_site_client.get(path)).headers, path


async def test_only_shared_responses_may_be_cached_at_the_edge(
    member_site_client: AsyncTestClient[Litestar], discord_state: dict
) -> None:
    await login_as(member_site_client, discord_state, discord_id=4242)
    assert EDGE_CACHE_HEADER in (await member_site_client.get("/api/discord/live")).headers
    for personal in ("/api/me", "/api/events"):
        assert EDGE_CACHE_HEADER not in (await member_site_client.get(personal)).headers, personal


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
