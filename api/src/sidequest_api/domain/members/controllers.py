"""The signed-in member's own profile, and the officers' member list."""

from litestar import Controller, get
from litestar.di import NamedDependency, Provide

from sidequest_api.domain.members.dependencies import provide_members_service
from sidequest_api.domain.members.services import MembersService
from sidequest_api.lib.discord import avatar_url
from sidequest_api.lib.member_auth import is_officer
from sidequest_common.models import Member
from sidequest_common.schemas import Me, MemberListing
from sidequest_common.settings import WebSettings


def _to_me(member: Member, web_settings: WebSettings) -> Me:
    return Me(
        id=member.id,
        discord_id=str(member.discord_id),
        username=member.username,
        display_name=member.display_name,
        avatar_url=avatar_url(member.discord_id, member.avatar_hash),
        is_guild_member=member.is_guild_member,
        is_officer=is_officer(member, web_settings.OFFICER_ROLE_IDS),
        battletag=member.battletag,
    )


class MembersController(Controller):
    """``/api/me`` and ``/api/members``."""

    path = "/api"
    tags = ["Members"]
    dependencies = {"members_service": Provide(provide_members_service)}

    @get("/me", operation_id="GetMe")
    async def get_me(
        self,
        authenticated_member: NamedDependency[Member],
        web_settings: NamedDependency[WebSettings],
    ) -> Me:
        """The signed-in member's profile. 401 if not logged in."""
        return _to_me(authenticated_member, web_settings)

    @get("/members", operation_id="ListMembers")
    async def list_members(
        self,
        current_officer: NamedDependency[Member],
        members_service: NamedDependency[MembersService],
        web_settings: NamedDependency[WebSettings],
    ) -> list[MemberListing]:
        """Officers only: everyone who has signed in, with their linked BattleTag for checking the guild roster."""
        del current_officer
        return [
            MemberListing(
                id=member.id,
                username=member.username,
                display_name=member.display_name,
                avatar_url=avatar_url(member.discord_id, member.avatar_hash),
                is_guild_member=member.is_guild_member,
                is_officer=is_officer(member, web_settings.OFFICER_ROLE_IDS),
                battletag=member.battletag,
                last_login_at=member.last_login_at,
            )
            for member in await members_service.list_for_officers()
        ]
