"""Litestar application factory: the one backend for the Discord bot, the website, and addons."""

from typing import TYPE_CHECKING

from litestar import Litestar, Router
from litestar.datastructures import State
from litestar.di import Provide
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin
from litestar.plugins.pydantic import PydanticPlugin

from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings

if TYPE_CHECKING:
    from pathlib import Path

    import httpx


def create_app(
    db_settings: DatabaseSettings | None = None,
    api_settings: APISettings | None = None,
    web_settings: WebSettings | None = None,
    *,
    website_dist: Path | None = None,
    discord_transport: httpx.BaseTransport | None = None,
    battlenet_transport: httpx.BaseTransport | None = None,
) -> Litestar:
    """Build the app. Settings default to the environment; tests pass their own. Schema comes from migrations.

    Routes: ``/api/guilds/{guild_id}/...`` (bot, requires ``X-API-Key``), ``/health``, ``/schema`` (OpenAPI docs),
    ``/auth`` (Discord sign-in, Battle.net linking), ``/api/me``, ``/api/members``, ``/api/events``, ``/api/addons``
    (member hub), and the website at ``/`` (``website_dist`` defaults to the repo's ``website/dist``).
    ``discord_transport``/``battlenet_transport`` let tests mock the Discord and Battle.net APIs.
    """
    from advanced_alchemy.extensions.litestar import SQLAlchemyPlugin

    from sidequest_api.domain import GUILD_API_PATH, guild_controllers, public_routes
    from sidequest_api.lib.auth import API_KEY_HEADER, api_key_guard
    from sidequest_api.lib.battlenet import BATTLENET_TRANSPORT_STATE_KEY
    from sidequest_api.lib.db import build_alchemy_config
    from sidequest_api.lib.discord import DISCORD_TRANSPORT_STATE_KEY
    from sidequest_api.lib.member_auth import (
        build_session_config,
        create_current_gm_provider,
        create_current_officer_provider,
        provide_authenticated_member,
        provide_current_member,
    )
    from sidequest_api.lib.website import DEFAULT_WEBSITE_DIST, is_vite_dev_mode, website_routes, website_vite_plugin

    db_settings = db_settings or DatabaseSettings()
    api_settings = api_settings or APISettings()
    web_settings = web_settings or WebSettings()
    guild_api = Router(
        path=GUILD_API_PATH,
        route_handlers=guild_controllers,
        guards=[api_key_guard(api_settings.KEY.get_secret_value())],
    )
    website_dev = is_vite_dev_mode()
    website_handlers = [] if website_dev else website_routes(website_dist or DEFAULT_WEBSITE_DIST)
    website_plugins = [website_vite_plugin()] if website_dev else []
    return Litestar(
        route_handlers=[guild_api, *public_routes, *website_handlers],
        plugins=[
            SQLAlchemyPlugin(config=build_alchemy_config(db_settings)),
            PydanticPlugin(prefer_alias=True),
            *website_plugins,
        ],
        middleware=[build_session_config(web_settings).middleware],
        dependencies={
            "web_settings": Provide(lambda: web_settings, sync_to_thread=False),
            "authenticated_member": Provide(provide_authenticated_member),
            "current_member": Provide(provide_current_member),
            "current_officer": Provide(create_current_officer_provider(web_settings.OFFICER_ROLE_IDS)),
            "current_gm": Provide(create_current_gm_provider(web_settings.GM_ROLE_IDS)),
        },
        state=State(
            {DISCORD_TRANSPORT_STATE_KEY: discord_transport, BATTLENET_TRANSPORT_STATE_KEY: battlenet_transport}
        ),
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
