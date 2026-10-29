"""GM-only console: member management detail, the unified activity log, and moderation case review/edit.

Gating is dependency-based (``current_gm``, registered app-wide in ``create_app``): declaring the parameter
resolves it, raising 401/403 before the handler body runs. See ``local://gm-console-contract.md``.
"""

from datetime import datetime
from typing import Annotated

from litestar import Controller, get, patch
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, FromQuery, JSONBody, QueryParameter

from sidequest_api.domain.gm.dependencies import provide_gm_service
from sidequest_api.domain.gm.services import GmService
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_common.models import Member
from sidequest_common.schemas import GmCase, GmCaseReasonUpdate, GmMember, GmMemberDetail, LogPage

DEFAULT_LOG_LIMIT = 50
MAX_LOG_LIMIT = 100


class GmController(Controller):
    """``/api/gm``."""

    path = "/api/gm"
    tags = ["GM Console"]
    dependencies = {"gm_service": Provide(provide_gm_service)}

    @get("/members", operation_id="ListGmMembers")
    async def list_members(
        self, current_gm: NamedDependency[Member], gm_service: NamedDependency[GmService]
    ) -> list[GmMember]:
        """Every signed-in member, Discord members first, then display name (casefold). 401/403 non-GM."""
        del current_gm
        return await gm_service.list_members()

    @get("/members/{member_id:int}", operation_id="GetGmMemberDetail")
    async def get_member_detail(
        self,
        member_id: FromPath[int],
        current_gm: NamedDependency[Member],
        gm_service: NamedDependency[GmService],
    ) -> GmMemberDetail:
        """One member's profile, signups, and cases. 401/403 non-GM, 404 unknown member."""
        del current_gm
        return await gm_service.get_member_detail(member_id)

    @get("/log", operation_id="GetGmLog")
    async def get_log(
        self,
        current_gm: NamedDependency[Member],
        gm_service: NamedDependency[GmService],
        kind: FromQuery[list[str] | None] = None,
        before: FromQuery[datetime | None] = None,
        limit: Annotated[int, QueryParameter(ge=1, le=MAX_LOG_LIMIT)] = DEFAULT_LOG_LIMIT,
    ) -> LogPage:
        """Merged activity log across sign-ups, sign-ins, Battle.net links, officer actions, and moderation."""
        del current_gm
        return await gm_service.get_log(kinds=kind, before=before, limit=limit)

    @get("/cases", operation_id="ListGmCases")
    async def list_cases(
        self,
        current_gm: NamedDependency[Member],
        gm_service: NamedDependency[GmService],
        user_id: FromQuery[int | None] = None,
    ) -> list[GmCase]:
        """Site-guild moderation cases, newest first, optionally only for ``user_id``."""
        del current_gm
        return await gm_service.list_cases(user_id=user_id)

    @patch("/cases/{case_number:int}", operation_id="UpdateGmCaseReason")
    async def update_case_reason(
        self,
        case_number: FromPath[int],
        data: JSONBody[GmCaseReasonUpdate],
        current_gm: NamedDependency[Member],
        gm_service: NamedDependency[GmService],
    ) -> GmCase:
        """Edit a case's reason. 401/403 non-GM, 404 unknown case. Writes a ``case.edit`` audit row."""
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
