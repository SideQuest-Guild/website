"""Member away date ranges.

``AwayController`` (signed in) is the member's own CRUD at ``/api/me/away``. ``AwayNowController`` is bot-key
only, mounted at ``/api/guilds/{guild_id}/away-now``: 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID``
(same rule as ``member_links``/``event_sync``), so a bot on the wrong server, or mid rolling-deploy against an API
without this route, doesn't grant the role to anyone.
"""

from uuid import UUID

from litestar import Controller, delete, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, JSONBody

from sidequest_api.domain.away.dependencies import provide_away_service
from sidequest_api.domain.away.services import AwayService
from sidequest_common.models import Member
from sidequest_common.schemas import AwayNowReport, AwayRangeIn, AwayRangeSchema
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class AwayController(Controller):
    """``/api/me/away``: the signed-in member's own away date ranges."""

    path = "/api/me/away"
    tags = ["Away"]
    dependencies = {"away_service": Provide(provide_away_service)}

    @get("/", operation_id="ListAway")
    async def list_away(
        self, current_member: NamedDependency[Member], away_service: NamedDependency[AwayService]
    ) -> list[AwayRangeSchema]:
        """The member's away ranges, soonest first; past ranges are pruned before the list is built."""
        ranges = await away_service.list_for_member(current_member)
        return [AwayRangeSchema.model_validate(away_range) for away_range in ranges]

    @post("/", operation_id="CreateAway", status_code=201)
    async def create_away(
        self,
        data: JSONBody[AwayRangeIn],
        current_member: NamedDependency[Member],
        away_service: NamedDependency[AwayService],
    ) -> AwayRangeSchema:
        """Add a new away range."""
        away_range = await away_service.add_range(current_member, data)
        return AwayRangeSchema.model_validate(away_range)

    @delete("/{range_id:uuid}", operation_id="DeleteAway")
    async def delete_away(
        self,
        range_id: FromPath[UUID],
        current_member: NamedDependency[Member],
        away_service: NamedDependency[AwayService],
    ) -> None:
        """Remove one of the member's own away ranges. 404 if it doesn't exist or belongs to someone else."""
        await away_service.delete_for_member(current_member, range_id)


class AwayNowController(Controller):
    """``/api/guilds/{guild_id}/away-now``: Discord ids of every member away today (America/Chicago)."""

    path = "/away-now"
    tags = ["Away"]
    dependencies = {"away_service": Provide(provide_away_service)}

    @get("/", operation_id="GetAwayNow")
    async def get_away_now(
        self,
        guild_id: FromPath[int],
        away_service: NamedDependency[AwayService],
        web_settings: NamedDependency[WebSettings],
    ) -> AwayNowReport:
        """Discord ids of members whose away range covers today. The bot owns ``away_role_id`` fully from this."""
        _require_site_guild(guild_id, web_settings)
        return AwayNowReport(discord_ids=await away_service.discord_ids_away_now())
