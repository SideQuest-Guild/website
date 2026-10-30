"""Member profile push, bot-key only. ``/api/guilds/{guild_id}/member-profiles``.

Keeps names, nick, avatar and roles in sync with Discord continuously (full sweep plus debounced event pushes from
the bot), rather than only at sign-in. Only existing ``Member`` rows are ever touched, never created. 404s for any
``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``member_links``/``guild_roles``).
"""

from litestar import Controller, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody

from sidequest_api.domain.member_profiles.dependencies import provide_member_profiles_service
from sidequest_api.domain.member_profiles.services import MemberProfilesService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import MemberProfilesReplace
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class MemberProfilesController(Controller):
    """``/api/guilds/{guild_id}/member-profiles``: the bot reports linked members' current Discord profiles."""

    path = "/member-profiles"
    tags = ["Member profiles"]
    dependencies = {"member_profiles_service": Provide(provide_member_profiles_service)}

    @put(
        "/",
        operation_id="SyncMemberProfiles",
        status_code=204,
        summary="Sync member Discord profiles",
        description=(
            "Updates existing members' names, nicknames, avatars, and roles, and marks departures. Unknown IDs "
            "are ignored. Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The profiles were synced.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server.")},
    )
    async def sync_profiles(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[MemberProfilesReplace],
        member_profiles_service: NamedDependency[MemberProfilesService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await member_profiles_service.sync_profiles(data.profiles, data.departed_ids)
