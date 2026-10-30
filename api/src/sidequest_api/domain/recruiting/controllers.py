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
    tags = ["Recruiting"]
    dependencies = {"recruiting_service": Provide(provide_recruiting_service)}

    @get("/", operation_id="GetRecruiting", response_headers=[EDGE_RECRUITING_CACHE], opt=SKIP_SESSION)
    async def get_recruiting(
        self, recruiting_service: NamedDependency[RecruitingService], web_settings: NamedDependency[WebSettings]
    ) -> Recruiting:
        """The guild's current recruiting needs, empty lists if nothing has ever been set."""
        return await recruiting_service.get_needs(web_settings.GUILD_ID)

    @put("/", operation_id="UpdateRecruiting")
    async def update_recruiting(
        self,
        data: JSONBody[RecruitingUpdate],
        recruiting_service: NamedDependency[RecruitingService],
        web_settings: NamedDependency[WebSettings],
        current_officer: NamedDependency[Member],
    ) -> Recruiting:
        """Replace the full set of wanted roles and classes (officer)."""
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
