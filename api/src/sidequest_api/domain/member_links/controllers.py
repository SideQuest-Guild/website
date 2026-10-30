"""Member link status, bot-key only. ``/api/guilds/{guild_id}/member-links``.

Every ``Member`` row is someone who has signed in on the site; the bot uses this to grant/revoke the signed-in
and Battle.net-linked roles. 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as
``event_sync``/``discord_live``).
"""

from litestar import Controller, get
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec

from sidequest_api.domain.member_links.dependencies import provide_member_links_service
from sidequest_api.domain.member_links.services import MemberLinksService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import MemberLink
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class MemberLinksController(Controller):
    """``/api/guilds/{guild_id}/member-links``: who has signed in, and who has also linked Battle.net."""

    path = "/member-links"
    tags = ["Member links"]
    dependencies = {"member_links_service": Provide(provide_member_links_service)}

    @get(
        "/",
        operation_id="ListMemberLinks",
        summary="List member link status",
        description=(
            "Returns every signed-in member's Discord ID, whether they have linked Battle.net, and whether a "
            "Game Master confirmed their roster status. Returns 404 for any guild_id other than the SideQuest "
            "server."
        ),
        response_description="The guild's member link statuses.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server.")},
    )
    async def list_member_links(
        self,
        guild_id: GuildIdPath,
        member_links_service: NamedDependency[MemberLinksService],
        web_settings: NamedDependency[WebSettings],
    ) -> list[MemberLink]:
        _require_site_guild(guild_id, web_settings)
        return [
            MemberLink(
                discord_id=member.discord_id,
                battlenet_linked=member.battlenet_id is not None,
                roster_confirmed=member.roster_confirmed_at is not None,
            )
            for member in await member_links_service.list_links()
        ]
