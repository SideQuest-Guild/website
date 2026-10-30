"""Hall of Heroes badge sync, bot-key only. ``/api/guilds/{guild_id}/badges``.

404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``member_links``/``discord_live``).
Recomputing and awarding runs on every ``GET /sync`` call: it's the bot's poll loop that drives it, and awarding
is idempotent, so polling it repeatedly is harmless.
"""

from litestar import Controller, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, JSONBody

from sidequest_api.domain.badges.dependencies import provide_badge_service
from sidequest_api.domain.badges.services import BadgeService
from sidequest_common.schemas import BadgeAck, BadgeSyncReport
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class BadgesController(Controller):
    """``/api/guilds/{guild_id}/badges``: badge role state and pending announcements for the bot."""

    path = "/badges"
    tags = ["Badges"]
    dependencies = {"badge_service": Provide(provide_badge_service)}

    @get("/sync", operation_id="SyncBadges")
    async def sync(
        self,
        guild_id: FromPath[int],
        badge_service: NamedDependency[BadgeService],
        web_settings: NamedDependency[WebSettings],
    ) -> BadgeSyncReport:
        """Recompute every member's badges, award any newly earned ones, and report role state + new announcements."""
        _require_site_guild(guild_id, web_settings)
        role_state, pending = await badge_service.sync(guild_id=guild_id)
        return BadgeSyncReport(role_state=role_state, pending=pending)

    @post("/ack", operation_id="AckBadgeAnnouncement", status_code=204)
    async def ack(
        self,
        guild_id: FromPath[int],
        data: JSONBody[BadgeAck],
        badge_service: NamedDependency[BadgeService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """Mark one member's badge as announced, so ``sync`` stops reporting it as pending."""
        _require_site_guild(guild_id, web_settings)
        await badge_service.ack(data.discord_id, data.badge_id)
