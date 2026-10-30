"""Member away date ranges.

``AwayController`` (signed in) is the member's own CRUD at ``/api/me/away``. ``AwayNowController`` is bot-key
only, mounted at ``/api/guilds/{guild_id}/away-now``: 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID``
(same rule as ``member_links``/``event_sync``), so a bot on the wrong server, or mid rolling-deploy against an API
without this route, doesn't grant the role to anyone.
"""

from typing import Annotated
from uuid import UUID

from litestar import Controller, delete, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.away.dependencies import provide_away_service
from sidequest_api.domain.away.services import AwayService
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_SIGNED_IN, SECURITY_SESSION, GuildIdPath
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
    tags = ["My away dates"]
    security = SECURITY_SESSION
    dependencies = {"away_service": Provide(provide_away_service)}

    @get(
        "/",
        operation_id="ListAway",
        summary="List my away dates",
        description=(
            "Returns the signed-in member's away ranges, soonest first. Past ranges are pruned before the "
            "list is built."
        ),
        response_description="The member's away ranges.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def list_away(
        self, current_member: NamedDependency[Member], away_service: NamedDependency[AwayService]
    ) -> list[AwayRangeSchema]:
        ranges = await away_service.list_for_member(current_member)
        return [AwayRangeSchema.model_validate(away_range) for away_range in ranges]

    @post(
        "/",
        operation_id="CreateAway",
        status_code=201,
        summary="Add an away date range",
        description="Adds a new away range for the signed-in member.",
        response_description="The new away range.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def create_away(
        self,
        data: JSONBody[AwayRangeIn],
        current_member: NamedDependency[Member],
        away_service: NamedDependency[AwayService],
    ) -> AwayRangeSchema:
        away_range = await away_service.add_range(current_member, data)
        return AwayRangeSchema.model_validate(away_range)

    @delete(
        "/{range_id:uuid}",
        operation_id="DeleteAway",
        summary="Remove an away date range",
        description="Removes one of the signed-in member's own away ranges.",
        response_description="The away range was removed.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            404: ResponseSpec(None, description="The away range does not exist or belongs to someone else."),
        },
    )
    async def delete_away(
        self,
        range_id: Annotated[UUID, Parameter(description="The away range's ID.")],
        current_member: NamedDependency[Member],
        away_service: NamedDependency[AwayService],
    ) -> None:
        await away_service.delete_for_member(current_member, range_id)


class AwayNowController(Controller):
    """``/api/guilds/{guild_id}/away-now``: Discord ids of every member away today (America/Chicago)."""

    path = "/away-now"
    tags = ["Away status"]
    dependencies = {"away_service": Provide(provide_away_service)}

    @get(
        "/",
        operation_id="GetAwayNow",
        summary="List members away today",
        description=(
            "Returns the Discord IDs of members whose away range covers today (America/Chicago). The bot owns "
            "the away role fully from this list. Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The Discord IDs of members away today.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server.")},
    )
    async def get_away_now(
        self,
        guild_id: GuildIdPath,
        away_service: NamedDependency[AwayService],
        web_settings: NamedDependency[WebSettings],
    ) -> AwayNowReport:
        _require_site_guild(guild_id, web_settings)
        return AwayNowReport(discord_ids=await away_service.discord_ids_away_now())
