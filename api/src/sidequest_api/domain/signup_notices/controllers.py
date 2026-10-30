"""New-signup officer notice outbox, and bot-key roster confirmation from a notice's Approve button.

Bot-key only, mounted at ``/api/guilds/{guild_id}``. Every route 404s for any ``guild_id`` other than
``WebSettings.GUILD_ID`` (same rule as ``event_sync``/``discord_live``).

The ``signup-notices/{member_id}/roster-confirmation`` routes do the same thing as the GM console's session-based
``PUT``/``DELETE /api/members/{member_id}/roster-confirmation``, but for the bot's "Approve" button on a signup
notice: the target is the notice's site member id (carried in the button's ``custom_id``), and the actor is
identified by Discord id instead of a cookie session, so the API independently checks the actor's last-known roles
(it never trusts the bot's own Discord-side role check alone).
"""

from typing import Annotated

from litestar import Controller, delete, get, post, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException, PermissionDeniedException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter
from sqlalchemy import select

from sidequest_api.domain.members.services import MembersService
from sidequest_api.domain.signup_notices.dependencies import provide_members_service
from sidequest_api.lib.discord import avatar_url
from sidequest_api.lib.member_auth import is_gm, is_officer
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.models import Member, OfficerAudit
from sidequest_common.schemas import (
    ConfirmByDiscordRequest,
    MemberListing,
    SignupNoticeAck,
    SignupNoticeCandidate,
    SignupNoticeResolution,
    SignupNoticesPage,
)
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


def _to_candidate(member: Member) -> SignupNoticeCandidate:
    return SignupNoticeCandidate(
        member_id=member.id,
        discord_id=str(member.discord_id),
        display_name=member.display_name,
        username=member.username,
        avatar_hash=member.avatar_hash,
        battletag=member.battletag,
        roster_confirmed=member.roster_confirmed_at is not None,
        created_at=member.created_at,
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


async def _confirmed_by_names(members_service: MembersService, member_ids: list[int]) -> dict[int, str | None]:
    """Latest ``roster.confirm`` audit actor name per member id, for members in ``member_ids``."""
    if not member_ids:
        return {}
    subject_ids = {str(member_id) for member_id in member_ids}
    statement = (
        select(OfficerAudit)
        .where(OfficerAudit.action == "roster.confirm", OfficerAudit.subject_id.in_(subject_ids))
        .order_by(OfficerAudit.created_at.desc())
    )
    rows = (await members_service.repository.session.execute(statement)).scalars()
    names: dict[int, str | None] = {}
    for row in rows:
        member_id = int(row.subject_id) if row.subject_id is not None else None
        if member_id is not None and member_id not in names:
            names[member_id] = row.actor_name
    return names


def _require_gm_actor(actor: Member | None, gm_role_ids: list[int]) -> Member:
    if actor is None or not is_gm(actor, gm_role_ids):
        msg = "GMs only"
        raise PermissionDeniedException(msg)
    return actor


class SignupNoticesController(Controller):
    """``/api/guilds/{guild_id}/signup-notices`` and ``/signup-notices/{member_id}/roster-confirmation``."""

    path = ""
    tags = ["Signup notices"]
    dependencies = {"members_service": Provide(provide_members_service)}

    @get(
        "/signup-notices",
        operation_id="ListSignupNotices",
        summary="List pending signup notices",
        description=(
            "Returns members needing a new signup notice posted, and posted notices whose message is now "
            "stale. Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The pending and resolved signup notices.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server.")},
    )
    async def list_signup_notices(
        self,
        guild_id: GuildIdPath,
        members_service: NamedDependency[MembersService],
        web_settings: NamedDependency[WebSettings],
    ) -> SignupNoticesPage:
        _require_site_guild(guild_id, web_settings)
        pending = await members_service.list_unnoticed()
        resolved_members = await members_service.list_unresolved_confirmations()
        confirmed_by = await _confirmed_by_names(members_service, [member.id for member in resolved_members])
        return SignupNoticesPage(
            pending=[_to_candidate(member) for member in pending],
            resolved=[
                SignupNoticeResolution(
                    member_id=member.id,
                    discord_id=str(member.discord_id),
                    display_name=member.display_name,
                    channel_id=str(member.officer_notice_channel_id),
                    message_id=str(member.officer_notice_message_id),
                    confirmed_by=confirmed_by.get(member.id),
                )
                for member in resolved_members
            ],
        )

    @post(
        "/signup-notices/{member_id:int}/ack",
        operation_id="AckSignupNotice",
        status_code=204,
        summary="Acknowledge a signup notice",
        description=(
            "Confirms the bot's posted message for a member now accurately reflects their current roster "
            "state. Returns 404 for any guild_id other than the SideQuest server, or an unknown member."
        ),
        response_description="The notice was acknowledged.",
        responses={
            404: ResponseSpec(
                None, description="This guild_id is not the SideQuest server, or the member has never signed in."
            )
        },
    )
    async def ack_signup_notice(
        self,
        guild_id: GuildIdPath,
        member_id: Annotated[int, Parameter(description="The site member's ID.")],
        data: JSONBody[SignupNoticeAck],
        members_service: NamedDependency[MembersService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        member = await members_service.get_for_officer_action(member_id)
        await members_service.ack_notice(member, channel_id=data.channel_id, message_id=data.message_id)

    @put(
        "/signup-notices/{member_id:int}/roster-confirmation",
        operation_id="ConfirmSignupNoticeMember",
        summary="Confirm a signup notice's member on the roster",
        description=(
            "Confirms the notice's member on the in-game roster, same as the GM console's confirm route, but "
            "identifies the actor by Discord ID for the bot's Approve button. Returns 403 unless the actor has a "
            "signed-in Member row holding a Quest Master role. Returns 404 for any guild_id other than the "
            "SideQuest server, or if member_id doesn't exist."
        ),
        response_description="The member's updated listing.",
        responses={
            403: ResponseSpec(None, description="The actor is not a Quest Master."),
            404: ResponseSpec(
                None, description="This guild_id is not the SideQuest server, or member_id doesn't exist."
            ),
        },
    )
    async def confirm_from_notice(
        self,
        guild_id: GuildIdPath,
        member_id: Annotated[int, Parameter(description="The site member's ID.")],
        data: JSONBody[ConfirmByDiscordRequest],
        members_service: NamedDependency[MembersService],
        web_settings: NamedDependency[WebSettings],
    ) -> MemberListing:
        _require_site_guild(guild_id, web_settings)
        member = await members_service.get_for_officer_action(member_id)
        actor = await members_service.get_one_or_none(discord_id=int(data.actor_discord_id))
        actor = _require_gm_actor(actor, web_settings.GM_ROLE_IDS)
        member = await members_service.confirm_roster(member)
        await record_officer_audit(
            members_service.repository.session,
            actor=actor,
            action="roster.confirm",
            subject_type="member",
            subject_id=str(member.id),
            summary=f"Confirmed {member.display_name} on the roster",
        )
        return _to_listing(member, web_settings)

    @delete(
        "/signup-notices/{member_id:int}/roster-confirmation",
        operation_id="UnconfirmSignupNoticeMember",
        status_code=200,
        summary="Clear a signup notice's member's roster confirmation",
        description=(
            "Clears the notice's member's roster confirmation, same as the GM console's unconfirm route, but "
            "identifies the actor by Discord ID. Returns 403 unless the actor has a signed-in Member row holding a "
            "Quest Master role. Returns 404 for any guild_id other than the SideQuest server, or if member_id "
            "doesn't exist."
        ),
        response_description="The member's updated listing.",
        responses={
            403: ResponseSpec(None, description="The actor is not a Quest Master."),
            404: ResponseSpec(
                None, description="This guild_id is not the SideQuest server, or member_id doesn't exist."
            ),
        },
    )
    async def unconfirm_from_notice(
        self,
        guild_id: GuildIdPath,
        member_id: Annotated[int, Parameter(description="The site member's ID.")],
        data: JSONBody[ConfirmByDiscordRequest],
        members_service: NamedDependency[MembersService],
        web_settings: NamedDependency[WebSettings],
    ) -> MemberListing:
        _require_site_guild(guild_id, web_settings)
        member = await members_service.get_for_officer_action(member_id)
        actor = await members_service.get_one_or_none(discord_id=int(data.actor_discord_id))
        actor = _require_gm_actor(actor, web_settings.GM_ROLE_IDS)
        member = await members_service.unconfirm_roster(member)
        await record_officer_audit(
            members_service.repository.session,
            actor=actor,
            action="roster.remove",
            subject_type="member",
            subject_id=str(member.id),
            summary=f"Removed {member.display_name} from the roster",
        )
        return _to_listing(member, web_settings)
