"""Litestar application factory: the one backend for the Discord bot, the website, and addons."""

from typing import TYPE_CHECKING

from litestar import Litestar, Router
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin

from sidequest_common.settings import APISettings, DatabaseSettings

if TYPE_CHECKING:
    from pathlib import Path


def create_app(
    db_settings: DatabaseSettings | None = None,
    api_settings: APISettings | None = None,
    *,
    website_dist: Path | None = None,
) -> Litestar:
    """Build the app. Settings default to the environment; tests pass their own. Schema comes from migrations.

    Routes: ``/api/guilds/{guild_id}/...`` (bot, requires ``X-API-Key``), ``/health``, ``/schema`` (OpenAPI docs),
    and the website at ``/`` (``website_dist`` defaults to the repo's ``website/dist``).
    """
    from advanced_alchemy.extensions.litestar import SQLAlchemyPlugin

    from sidequest_api.domain import GUILD_API_PATH, guild_controllers, public_routes
    from sidequest_api.lib.auth import API_KEY_HEADER, api_key_guard
    from sidequest_api.lib.db import build_alchemy_config
    from sidequest_api.lib.website import DEFAULT_WEBSITE_DIST, website_routes

    db_settings = db_settings or DatabaseSettings()
    api_settings = api_settings or APISettings()

    guild_api = Router(
        path=GUILD_API_PATH,
        route_handlers=guild_controllers,
        guards=[api_key_guard(api_settings.KEY.get_secret_value())],
    )
    return Litestar(
        route_handlers=[guild_api, *public_routes, *website_routes(website_dist or DEFAULT_WEBSITE_DIST)],
        plugins=[SQLAlchemyPlugin(config=build_alchemy_config(db_settings))],
        openapi_config=OpenAPIConfig(
            title="SideQuest Guild API",
            version="0.1.0",
            description=(
                "Backend for the SideQuest Guild website and Discord bot. "
                f"`/api/guilds/...` endpoints are for the bot and require the `{API_KEY_HEADER}` header."
            ),
            path="/schema",
            render_plugins=[ScalarRenderPlugin()],
        ),
        debug=api_settings.DEBUG,
    )
