"""Recruitment drive endpoints: a drive's detail and leaderboard, and officer payout review.

Session-gated routes use dependency-based gating (``current_member``/``current_officer``, registered app-wide in
``create_app``): declaring the parameter resolves it, raising 401/403 before the handler body runs. See
``local://recruitment-contract.md``.
"""

from typing import Annotated
from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.recruitment.dependencies import provide_recruitment_service
from sidequest_api.domain.recruitment.services import RecruitmentService
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import RecruitmentDrive, RecruitPayout, RecruitPayoutMarkPaid

_EVENT_ID = Annotated[UUID, Parameter(description="The event's ID.")]


class RecruitmentController(Controller):
    """``/api/events/{event_id}/recruitment`` and ``/api/recruitment/payouts``."""

    path = "/api"
    dependencies = {"recruitment_service": Provide(provide_recruitment_service)}

    @get(
        "/events/{event_id:uuid}/recruitment",
        operation_id="GetRecruitmentDrive",
        tags=["Recruitment drives"],
        security=SECURITY_SESSION,
        summary="Get a recruitment drive",
        description=(
            "Returns a recruitment drive's totals, leaderboard, and recruit rows, freshly evaluated. A guild "
            "member must be signed in. 404 if the event is not a recruitment drive."
        ),
        response_description="The drive's totals, leaderboard, and recruit rows.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            404: ResponseSpec(None, description="No recruitment drive with that event ID."),
        },
    )
    async def get_drive(
        self,
        event_id: _EVENT_ID,
        recruitment_service: NamedDependency[RecruitmentService],
        current_member: NamedDependency[Member],
    ) -> RecruitmentDrive:
        del current_member
        return await recruitment_service.get_drive(event_id)

    @get(
        "/recruitment/payouts",
        operation_id="ListRecruitPayouts",
        tags=["Recruitment drives"],
        security=SECURITY_SESSION,
        summary="List recruit payouts",
        description=(
            "Returns settled drives' owed and already-paid totals per inviter, unpaid first. An officer must "
            "be signed in."
        ),
        response_description="The settled drives' payouts.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def list_payouts(
        self,
        recruitment_service: NamedDependency[RecruitmentService],
        current_officer: NamedDependency[Member],
    ) -> list[RecruitPayout]:
        del current_officer
        return await recruitment_service.list_payouts()

    @post(
        "/recruitment/payouts/paid",
        operation_id="MarkRecruitPayoutPaid",
        status_code=204,
        tags=["Recruitment drives"],
        security=SECURITY_SESSION,
        summary="Mark a recruit payout paid",
        description=(
            "Marks an inviter's qualified, unpaid recruits in a drive paid via the site. Idempotent: marking an "
            "already-paid inviter/drive does nothing. An officer must be signed in. Writes a "
            "`recruitment.mark_paid` audit row."
        ),
        response_description="The payout was marked paid.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def mark_paid(
        self,
        data: JSONBody[RecruitPayoutMarkPaid],
        recruitment_service: NamedDependency[RecruitmentService],
        current_officer: NamedDependency[Member],
    ) -> None:
        await recruitment_service.mark_paid(data.event_id, data.inviter, current_officer.display_name)
        await record_officer_audit(
            recruitment_service.session,
            actor=current_officer,
            action="recruitment.mark_paid",
            subject_type="recruitment_drive",
            subject_id=str(data.event_id),
            summary=f"Marked {data.inviter}'s recruit payout paid",
        )
