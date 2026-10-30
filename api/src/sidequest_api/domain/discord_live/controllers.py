"""Live Discord presence/voice-channel counts. The bot reports, the website reads.

``DiscordLiveController`` is bot-key only, mounted at ``/api/guilds/{guild_id}/live``: every route 404s for any
``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``event_sync``). ``DiscordLivePublicController`` is
public, at ``/api/discord/live``, and never 404s: missing or stale data reports as empty counts.
"""

from litestar import Controller, get, put
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody

from sidequest_api.domain.discord_live.dependencies import provide_discord_live_service
from sidequest_api.domain.discord_live.services import DiscordLiveService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_common.schemas import DiscordLive, DiscordLiveReport
from sidequest_common.settings import WebSettings

# Same counts for every visitor, refreshed by the bot about once a minute: Cloudflare may serve it for 15 seconds
# (then stale while one fetch refreshes it). Cloudflare strips this header, so browsers always ask again.
EDGE_LIVE_CACHE = ResponseHeader(name=EDGE_CACHE_HEADER, value="max-age=15, stale-while-revalidate=60")


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class DiscordLiveController(Controller):
    """``/api/guilds/{guild_id}/live``: the bot reports the guild's live presence/voice counts."""

    path = "/live"
    tags = ["Discord live"]
    dependencies = {"discord_live_service": Provide(provide_discord_live_service)}

    @put(
        "/",
        operation_id="ReportDiscordLive",
        status_code=204,
        summary="Report live Discord presence",
        description=(
            "Replaces the guild's stored live voice and member counts. The report timestamp is set to now. "
            "Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The live report was stored.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server.")},
    )
    async def report_live(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[DiscordLiveReport],
        discord_live_service: NamedDependency[DiscordLiveService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await discord_live_service.upsert_report(guild_id, data)


class DiscordLivePublicController(Controller):
    """``/api/discord/live``: the website's public read of the site guild's live status."""

    path = "/api/discord"
    tags = ["Discord status"]
    dependencies = {"discord_live_service": Provide(provide_discord_live_service)}

    @get(
        "/live",
        operation_id="GetDiscordLive",
        response_headers=[EDGE_LIVE_CACHE],
        opt=SKIP_SESSION,
        summary="Get live Discord status",
        description=(
            "Returns the site guild's live voice and member counts. Reports empty counts, not 404, if the bot "
            "has not reported recently."
        ),
        response_description="The site guild's live status.",
    )
    async def get_live(
        self,
        discord_live_service: NamedDependency[DiscordLiveService],
        web_settings: NamedDependency[WebSettings],
    ) -> DiscordLive:
        return await discord_live_service.get_live(web_settings.GUILD_ID)
