"""Member profile push, bot-key only. ``/api/guilds/{guild_id}/member-profiles``.

Keeps names, nick, avatar and roles in sync with Discord continuously (full sweep plus debounced event pushes from
the bot), rather than only at sign-in. Only existing ``Member`` rows are ever touched, never created. 404s for any
``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``member_links``/``guild_roles``).
"""

from litestar import Controller, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, JSONBody

from sidequest_api.domain.member_profiles.dependencies import provide_member_profiles_service
from sidequest_api.domain.member_profiles.services import MemberProfilesService
from sidequest_common.schemas import MemberProfilesReplace
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class MemberProfilesController(Controller):
    """``/api/guilds/{guild_id}/member-profiles``: the bot reports linked members' current Discord profiles."""

    path = "/member-profiles"
    tags = ["Member Profiles"]
    dependencies = {"member_profiles_service": Provide(provide_member_profiles_service)}

    @put("/", operation_id="SyncMemberProfiles", status_code=204)
    async def sync_profiles(
        self,
        guild_id: FromPath[int],
        data: JSONBody[MemberProfilesReplace],
        member_profiles_service: NamedDependency[MemberProfilesService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """Update existing members' profiles and mark departures; unknown ids are ignored."""
        _require_site_guild(guild_id, web_settings)
        await member_profiles_service.sync_profiles(data.profiles, data.departed_ids)
