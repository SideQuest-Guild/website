"""The signed-in member's own profile, and GM roster confirmation."""

from litestar import Controller, Request, delete, get, put
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath

from sidequest_api.domain.members.dependencies import provide_members_service
from sidequest_api.domain.members.services import MembersService
from sidequest_api.lib.discord import avatar_url
from sidequest_api.lib.member_auth import is_gm, is_officer
from sidequest_api.lib.officer_audit import record_officer_audit
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
        is_gm=is_gm(member, web_settings.GM_ROLE_IDS),
        battletag=member.battletag,
        roster_confirmed=member.roster_confirmed_at is not None,
    )


def _to_listing(member: Member, web_settings: WebSettings) -> MemberListing:
    return MemberListing(
        id=member.id,
        username=member.username,
        display_name=member.display_name,
        avatar_url=avatar_url(member.discord_id, member.avatar_hash),
        is_guild_member=member.is_guild_member,
        is_officer=is_officer(member, web_settings.OFFICER_ROLE_IDS),
        battletag=member.battletag,
        roster_confirmed=member.roster_confirmed_at is not None,
        last_login_at=member.last_login_at,
    )


class MembersController(Controller):
    """``/api/me`` and GM roster confirmation."""

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

    @delete("/me", operation_id="DeleteMe", status_code=204)
    async def delete_me(
        self,
        request: Request,
        authenticated_member: NamedDependency[Member],
        members_service: NamedDependency[MembersService],
    ) -> None:
        """Delete the signed-in member's account: the member row, their event signups, and the session cookie.

        401 if not logged in. This is the site's equivalent of unlinking Discord; signing in again afterwards
        creates a fresh member.
        """
        await members_service.delete_account(authenticated_member)
        request.clear_session()

    @put("/members/{member_id:int}/roster-confirmation", operation_id="ConfirmMemberRoster")
    async def confirm_member_roster(
        self,
        member_id: FromPath[int],
        current_gm: NamedDependency[Member],
        members_service: NamedDependency[MembersService],
        web_settings: NamedDependency[WebSettings],
    ) -> MemberListing:
        """GMs only: mark a member confirmed on the in-game guild roster.

        Idempotent: keeps the first confirmation timestamp if already confirmed. 401 signed out, 403 non-GM,
        404 unknown member id.
        """
        member = await members_service.get_for_officer_action(member_id)
        member = await members_service.confirm_roster(member)
        await record_officer_audit(
            members_service.repository.session,
            actor=current_gm,
            action="roster.confirm",
            subject_type="member",
            subject_id=str(member_id),
            summary=f"Confirmed {member.display_name} on the roster",
        )
        return _to_listing(member, web_settings)

    @delete("/members/{member_id:int}/roster-confirmation", operation_id="UnconfirmMemberRoster", status_code=200)
    async def unconfirm_member_roster(
        self,
        member_id: FromPath[int],
        current_gm: NamedDependency[Member],
        members_service: NamedDependency[MembersService],
        web_settings: NamedDependency[WebSettings],
    ) -> MemberListing:
        """GMs only: clear a member's roster confirmation. 401 signed out, 403 non-GM, 404 unknown id."""
        member = await members_service.get_for_officer_action(member_id)
        member = await members_service.unconfirm_roster(member)
        await record_officer_audit(
            members_service.repository.session,
            actor=current_gm,
            action="roster.remove",
            subject_type="member",
            subject_id=str(member_id),
            summary=f"Removed {member.display_name} from the roster",
        )
        return _to_listing(member, web_settings)
