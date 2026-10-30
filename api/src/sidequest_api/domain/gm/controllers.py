"""GM-only console: member management detail, the unified activity log, and moderation case review/edit.

Gating is dependency-based (``current_gm``, registered app-wide in ``create_app``): declaring the parameter
resolves it, raising 401/403 before the handler body runs. See ``local://gm-console-contract.md``.
"""

from datetime import datetime
from typing import Annotated

from litestar import Controller, get, patch
from litestar.di import NamedDependency, Provide
from litestar.params import JSONBody, Parameter, QueryParameter

from sidequest_api.domain.gm.dependencies import provide_gm_service
from sidequest_api.domain.gm.services import GmService
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import NOT_A_GM, NOT_SIGNED_IN, SECURITY_SESSION, ResponseSpec
from sidequest_common.models import Member
from sidequest_common.schemas import GmCase, GmCaseReasonUpdate, GmMember, GmMemberDetail, LogPage

DEFAULT_LOG_LIMIT = 50
MAX_LOG_LIMIT = 100


class GmController(Controller):
    """``/api/gm``."""

    path = "/api/gm"
    tags = ["GM console"]
    security = SECURITY_SESSION
    dependencies = {"gm_service": Provide(provide_gm_service)}

    @get(
        "/members",
        operation_id="ListGmMembers",
        summary="List members",
        description="Returns every signed-in member, Discord members first, then sorted by display name.",
        response_description="The members.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_GM},
    )
    async def list_members(
        self, current_gm: NamedDependency[Member], gm_service: NamedDependency[GmService]
    ) -> list[GmMember]:
        del current_gm
        return await gm_service.list_members()

    @get(
        "/members/{member_id:int}",
        operation_id="GetGmMemberDetail",
        summary="Get a member's detail",
        description="Returns one member's profile, event signups, and moderation cases.",
        response_description="The member's detail.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_GM,
            404: ResponseSpec(None, description="Unknown member."),
        },
    )
    async def get_member_detail(
        self,
        member_id: Annotated[int, Parameter(description="The member's ID.")],
        current_gm: NamedDependency[Member],
        gm_service: NamedDependency[GmService],
    ) -> GmMemberDetail:
        del current_gm
        return await gm_service.get_member_detail(member_id)

    @get(
        "/log",
        operation_id="GetGmLog",
        summary="Get the activity log",
        description=(
            "Returns a merged activity log across event sign-ups, sign-ins, Battle.net links, officer actions, "
            "and moderation."
        ),
        response_description="A page of log entries, newest first.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_GM},
    )
    async def get_log(
        self,
        current_gm: NamedDependency[Member],
        gm_service: NamedDependency[GmService],
        kind: Annotated[list[str] | None, Parameter(description="Only return entries of these kinds.")] = None,
        before: Annotated[datetime | None, Parameter(description="Only return entries before this time.")] = None,
        limit: Annotated[int, QueryParameter(ge=1, le=MAX_LOG_LIMIT, description="Max entries to return.")] = (
            DEFAULT_LOG_LIMIT
        ),
    ) -> LogPage:
        del current_gm
        return await gm_service.get_log(kinds=kind, before=before, limit=limit)

    @get(
        "/cases",
        operation_id="ListGmCases",
        summary="List moderation cases",
        description="Returns site-guild moderation cases, newest first, optionally filtered to one user.",
        response_description="The moderation cases.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_GM},
    )
    async def list_cases(
        self,
        current_gm: NamedDependency[Member],
        gm_service: NamedDependency[GmService],
        user_id: Annotated[int | None, Parameter(description="Only list cases for this Discord user ID.")] = None,
    ) -> list[GmCase]:
        del current_gm
        return await gm_service.list_cases(user_id=user_id)

    @patch(
        "/cases/{case_number:int}",
        operation_id="UpdateGmCaseReason",
        summary="Edit a moderation case's reason",
        description="Edits a case's reason and writes a `case.edit` audit row.",
        response_description="The updated case.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_GM,
            404: ResponseSpec(None, description="Unknown case."),
        },
    )
    async def update_case_reason(
        self,
        case_number: Annotated[int, Parameter(description="The case's number.")],
        data: JSONBody[GmCaseReasonUpdate],
        current_gm: NamedDependency[Member],
        gm_service: NamedDependency[GmService],
    ) -> GmCase:
        case = await gm_service.update_case_reason(case_number, data.reason)
        await record_officer_audit(
            gm_service.session,
            actor=current_gm,
            action="case.edit",
            subject_type="case",
            subject_id=str(case_number),
            summary=f"Edited the reason on case #{case_number}",
        )
        return case
