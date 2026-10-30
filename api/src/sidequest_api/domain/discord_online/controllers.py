"""``/api/discord/online``: the signed-in member hub's read of Discord's public server widget.

Members only (401 signed out, 403 signed in but not a guild member). Never edge-cached: it varies by session, and
Discord's widget data is already cached in-process for ``CACHE_TTL_SECONDS`` (see ``services.py``).
"""

import httpx
from litestar import Controller, get
from litestar.di import NamedDependency, Provide

from sidequest_api.domain.discord_online.services import DiscordOnlineService
from sidequest_api.lib.discord import provide_discord_client
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import DiscordOnline
from sidequest_common.settings import WebSettings


def provide_discord_online_service(discord_client: NamedDependency[httpx.AsyncClient]) -> DiscordOnlineService:
    """Build the ``DiscordOnlineService`` for this request from its already-provided Discord client."""
    return DiscordOnlineService(discord_client)


class DiscordOnlineController(Controller):
    """``/api/discord/online``: who's online in the guild's Discord right now, for signed-in guild members."""

    path = "/api/discord"
    tags = ["Discord presence"]
    security = SECURITY_SESSION
    dependencies = {
        "discord_client": Provide(provide_discord_client),
        "discord_online_service": Provide(provide_discord_online_service, sync_to_thread=False),
    }

    @get(
        "/online",
        operation_id="GetDiscordOnline",
        summary="Get who is online in Discord",
        description="Returns the guild's Discord widget roster: each member's name, status, avatar, and activity.",
        response_description="The guild's live Discord roster.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def get_online(
        self,
        current_member: NamedDependency[Member],
        discord_online_service: NamedDependency[DiscordOnlineService],
        web_settings: NamedDependency[WebSettings],
    ) -> DiscordOnline:
        del current_member
        return await discord_online_service.get_online(web_settings.GUILD_ID)
