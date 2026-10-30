"""Hall of Heroes badge sync, bot-key only. ``/api/guilds/{guild_id}/badges``.

404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``member_links``/``discord_live``).
Recomputing and awarding runs on every ``GET /sync`` call: it's the bot's poll loop that drives it, and awarding
is idempotent, so polling it repeatedly is harmless.
"""

from litestar import Controller, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody

from sidequest_api.domain.badges.dependencies import provide_badge_service
from sidequest_api.domain.badges.services import BadgeService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import BadgeAck, BadgeSyncReport
from sidequest_common.settings import WebSettings

_NOT_SITE_GUILD = ResponseSpec(None, description="This guild_id is not the SideQuest server.")


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class BadgesController(Controller):
    """``/api/guilds/{guild_id}/badges``: badge role state and pending announcements for the bot."""

    path = "/badges"
    tags = ["Badges"]
    dependencies = {"badge_service": Provide(provide_badge_service)}

    @get(
        "/sync",
        operation_id="SyncBadges",
        summary="Sync badges",
        description=(
            "Recomputes every member's badges, awards any newly earned ones, and reports role state plus new "
            "announcements. Awarding is idempotent, so polling this repeatedly is harmless. Returns 404 for any "
            "guild_id other than the SideQuest server."
        ),
        response_description="The badge role state and pending announcements.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def sync(
        self,
        guild_id: GuildIdPath,
        badge_service: NamedDependency[BadgeService],
        web_settings: NamedDependency[WebSettings],
    ) -> BadgeSyncReport:
        _require_site_guild(guild_id, web_settings)
        role_state, pending = await badge_service.sync(guild_id=guild_id)
        return BadgeSyncReport(role_state=role_state, pending=pending)

    @post(
        "/ack",
        operation_id="AckBadgeAnnouncement",
        status_code=204,
        summary="Acknowledge a badge announcement",
        description=(
            "Marks one member's badge as announced, so future syncs stop reporting it as pending. Returns 404 "
            "for any guild_id other than the SideQuest server."
        ),
        response_description="The badge announcement was acknowledged.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def ack(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[BadgeAck],
        badge_service: NamedDependency[BadgeService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await badge_service.ack(data.discord_id, data.badge_id)
