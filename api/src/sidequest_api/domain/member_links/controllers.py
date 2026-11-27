"""Member link status, bot-key only. ``/api/guilds/{guild_id}/member-links``.

Most ``Member`` rows are someone who has signed in on the site; one exists without signing in when a Quest Master
confirms them from Discord (``signed_in`` is false for those). The bot uses this to grant/revoke the signed-in,
Battle.net-linked and roster roles, and the guild rank roles (from ``guild_ranks``/``battlenet_guild_ranks``).
404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as
``event_sync``/``discord_live``).
"""

from typing import Annotated

from litestar import Controller, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import Parameter

from sidequest_api.domain.member_links.dependencies import provide_member_links_service
from sidequest_api.domain.member_links.services import MemberLinksService, MemberRanks
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import MemberLink
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class MemberLinksController(Controller):
    """``/api/guilds/{guild_id}/member-links``: sign-in and Battle.net link status for every known member."""

    path = "/member-links"
    tags = ["Member links"]
    dependencies = {"member_links_service": Provide(provide_member_links_service)}

    @get(
        "/",
        operation_id="ListMemberLinks",
        summary="List member link status",
        description=(
            "Returns every known member's Discord ID, whether they have signed in on the site, whether they have "
            "linked Battle.net, whether a Game Master confirmed their roster status, and the in-game guild ranks "
            "their characters hold on the Battle.net guild roster. Returns 404 for any guild_id other than the "
            "SideQuest server."
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
        members = await member_links_service.list_links()
        ranks = await member_links_service.member_ranks(members)
        characters = await member_links_service.guild_characters(members)
        no_ranks = MemberRanks()
        return [
            MemberLink(
                discord_id=member.discord_id,
                battlenet_linked=member.battlenet_id is not None,
                roster_confirmed=member.roster_confirmed_at is not None,
                signed_in=member.last_login_at is not None,
                guild_ranks=ranks.get(member.id, no_ranks).all,
                battlenet_guild_ranks=ranks.get(member.id, no_ranks).battlenet,
                guild_characters=characters.get(member.id, []),
                character_nick_done=member.character_nick_at is not None,
            )
            for member in members
        ]

    @post(
        "/{discord_id:int}/character-nick",
        operation_id="MarkMemberCharacterNick",
        status_code=204,
        summary="Record the bot's one character nickname call",
        description=(
            "Records that the bot set this member's Discord nickname to the guild character they joined on, or "
            "left the nickname they already had; it never renames them again. Idempotent. Returns 404 for any "
            "guild_id other than the SideQuest server, or an unknown member."
        ),
        response_description="Recorded.",
        responses={404: ResponseSpec(None, description="Not the SideQuest server, or no member with this Discord ID.")},
    )
    async def mark_character_nick(
        self,
        guild_id: GuildIdPath,
        discord_id: Annotated[int, Parameter(description="The member's Discord ID.")],
        member_links_service: NamedDependency[MemberLinksService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        if await member_links_service.mark_character_nick(discord_id) is None:
            msg = f"No member {discord_id}"
            raise NotFoundException(msg)
