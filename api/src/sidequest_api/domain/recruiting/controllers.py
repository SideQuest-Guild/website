"""Recruiting needs: public read, officer manage.

Mounted at ``/api/recruiting`` (no guild id in the path: the site only ever serves one guild, same as
``/api/discord/live``). The bot reads the same public GET for the guest-welcome DM.
"""

from litestar import Controller, get, put
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.params import JSONBody

from sidequest_api.domain.recruiting.dependencies import provide_recruiting_service
from sidequest_api.domain.recruiting.services import RecruitingService
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import Recruiting, RecruitingUpdate
from sidequest_common.settings import WebSettings

# Same answer for every visitor, changed only when an officer saves: Cloudflare may serve it for 60 seconds (then
# stale while one fetch refreshes it). Cloudflare strips this header, so browsers always ask again.
EDGE_RECRUITING_CACHE = ResponseHeader(name=EDGE_CACHE_HEADER, value="max-age=60, stale-while-revalidate=300")


class RecruitingController(Controller):
    """``/api/recruiting``."""

    path = "/api/recruiting"
    dependencies = {"recruiting_service": Provide(provide_recruiting_service)}

    @get(
        "/",
        operation_id="GetRecruiting",
        response_headers=[EDGE_RECRUITING_CACHE],
        opt=SKIP_SESSION,
        tags=["Recruiting"],
        summary="Get recruiting needs",
        description=(
            "Returns the guild's current recruiting needs. Roles and classes are empty lists if nothing has ever "
            "been set."
        ),
        response_description="The guild's recruiting needs.",
    )
    async def get_recruiting(
        self, recruiting_service: NamedDependency[RecruitingService], web_settings: NamedDependency[WebSettings]
    ) -> Recruiting:
        return await recruiting_service.get_needs(web_settings.GUILD_ID)

    @put(
        "/",
        operation_id="UpdateRecruiting",
        tags=["Recruiting needs"],
        security=SECURITY_SESSION,
        summary="Set recruiting needs",
        description="Replaces the full set of wanted roles and classes. An officer must be signed in.",
        response_description="The updated recruiting needs.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def update_recruiting(
        self,
        data: JSONBody[RecruitingUpdate],
        recruiting_service: NamedDependency[RecruitingService],
        web_settings: NamedDependency[WebSettings],
        current_officer: NamedDependency[Member],
    ) -> Recruiting:
        needs = await recruiting_service.replace_needs(web_settings.GUILD_ID, data)
        await record_officer_audit(
            recruiting_service.repository.session,
            actor=current_officer,
            action="recruiting.update",
            subject_type="recruiting",
            subject_id=None,
            summary=f"Updated recruiting needs ({len(needs.roles)} role(s), {len(needs.classes)} class(es))",
        )
        return needs
