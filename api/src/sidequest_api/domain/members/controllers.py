"""The signed-in member's own profile."""

from litestar import Controller, get
from litestar.di import NamedDependency

from sidequest_api.lib.discord import avatar_url
from sidequest_common.models import Member
from sidequest_common.schemas import Me
from sidequest_common.settings import WebSettings


def _to_me(member: Member, web_settings: WebSettings) -> Me:
    is_officer = bool(set(member.roles) & set(web_settings.OFFICER_ROLE_IDS))
    return Me(
        id=member.id,
        discord_id=str(member.discord_id),
        username=member.username,
        display_name=member.display_name,
        avatar_url=avatar_url(member.discord_id, member.avatar_hash),
        is_guild_member=member.is_guild_member,
        is_officer=is_officer,
    )


class MembersController(Controller):
    """``/api/me``."""

    path = "/api"
    tags = ["Members"]

    @get("/me", operation_id="GetMe")
    async def get_me(
        self,
        authenticated_member: NamedDependency[Member],
        web_settings: NamedDependency[WebSettings],
    ) -> Me:
        """The signed-in member's profile. 401 if not logged in."""
        return _to_me(authenticated_member, web_settings)
