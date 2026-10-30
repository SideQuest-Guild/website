"""The signed-in member's own profile, and GM roster confirmation."""

from typing import Annotated

from litestar import Controller, Request, delete, get, put
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import Parameter

from sidequest_api.domain.members.dependencies import provide_members_service
from sidequest_api.domain.members.services import MembersService
from sidequest_api.lib.discord import avatar_url
from sidequest_api.lib.member_auth import is_gm, is_officer
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import NOT_A_GM, NOT_SIGNED_IN, SECURITY_SESSION
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
    dependencies = {"members_service": Provide(provide_members_service)}

    @get(
        "/me",
        operation_id="GetMe",
        tags=["My account"],
        security=SECURITY_SESSION,
        summary="Get my profile",
        description="Returns the signed-in member's own profile.",
        response_description="The signed-in member's profile.",
        responses={401: NOT_SIGNED_IN},
    )
    async def get_me(
        self,
        authenticated_member: NamedDependency[Member],
        web_settings: NamedDependency[WebSettings],
    ) -> Me:
        return _to_me(authenticated_member, web_settings)

    @delete(
        "/me",
        operation_id="DeleteMe",
        status_code=204,
        tags=["My account"],
        security=SECURITY_SESSION,
        summary="Delete my account",
        description=(
            "Deletes the signed-in member's account, their event signups, and the session cookie. This is "
            "the site's equivalent of unlinking Discord. Signing in again afterwards creates a fresh member."
        ),
        response_description="The account was deleted.",
        responses={401: NOT_SIGNED_IN},
    )
    async def delete_me(
        self,
        request: Request,
        authenticated_member: NamedDependency[Member],
        members_service: NamedDependency[MembersService],
    ) -> None:
        await members_service.delete_account(authenticated_member)
        request.clear_session()

    @put(
        "/members/{member_id:int}/roster-confirmation",
        operation_id="ConfirmMemberRoster",
        tags=["Roster confirmation"],
        security=SECURITY_SESSION,
        summary="Confirm a member's roster status",
        description=(
            "Marks a member confirmed on the in-game guild roster. Only a Quest Master or Quest Guide may "
            "call this. The call is idempotent and keeps the first confirmation timestamp if the member is "
            "already confirmed."
        ),
        response_description="The member's updated listing.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_GM,
            404: ResponseSpec(None, description="No member has this ID."),
        },
    )
    async def confirm_member_roster(
        self,
        member_id: Annotated[int, Parameter(description="The member's database ID.")],
        current_gm: NamedDependency[Member],
        members_service: NamedDependency[MembersService],
        web_settings: NamedDependency[WebSettings],
    ) -> MemberListing:
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

    @delete(
        "/members/{member_id:int}/roster-confirmation",
        operation_id="UnconfirmMemberRoster",
        status_code=200,
        tags=["Roster confirmation"],
        security=SECURITY_SESSION,
        summary="Clear a member's roster status",
        description=(
            "Clears a member's confirmed in-game guild roster status. Only a Quest Master or Quest Guide may call this."
        ),
        response_description="The member's updated listing.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_GM,
            404: ResponseSpec(None, description="No member has this ID."),
        },
    )
    async def unconfirm_member_roster(
        self,
        member_id: Annotated[int, Parameter(description="The member's database ID.")],
        current_gm: NamedDependency[Member],
        members_service: NamedDependency[MembersService],
        web_settings: NamedDependency[WebSettings],
    ) -> MemberListing:
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
