"""Member link status, bot-key only. ``/api/guilds/{guild_id}/member-links``.

Every ``Member`` row is someone who has signed in on the site; the bot uses this to grant/revoke the signed-in
and Battle.net-linked roles. 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as
``event_sync``/``discord_live``).
"""

from litestar import Controller, get
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath

from sidequest_api.domain.member_links.dependencies import provide_member_links_service
from sidequest_api.domain.member_links.services import MemberLinksService
from sidequest_common.schemas import MemberLink
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class MemberLinksController(Controller):
    """``/api/guilds/{guild_id}/member-links``: who has signed in, and who has also linked Battle.net."""

    path = "/member-links"
    tags = ["Member Links"]
    dependencies = {"member_links_service": Provide(provide_member_links_service)}

    @get("/", operation_id="ListMemberLinks")
    async def list_member_links(
        self,
        guild_id: FromPath[int],
        member_links_service: NamedDependency[MemberLinksService],
        web_settings: NamedDependency[WebSettings],
    ) -> list[MemberLink]:
        """Every signed-in member's Discord id, whether they've linked Battle.net, and whether a GM confirmed them."""
        _require_site_guild(guild_id, web_settings)
        return [
            MemberLink(
                discord_id=member.discord_id,
                battlenet_linked=member.battlenet_id is not None,
                roster_confirmed=member.roster_confirmed_at is not None,
            )
            for member in await member_links_service.list_links()
        ]
