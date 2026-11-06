"""``/api/pvp``: the members-only battleground match history and PvP boards."""

from typing import Annotated
from uuid import UUID

from litestar import Controller, get
from litestar.di import NamedDependency, Provide
from litestar.params import Parameter, QueryParameter

from sidequest_api.domain.pvp.dependencies import provide_pvp_service
from sidequest_api.domain.pvp.services import PvpService
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_SIGNED_IN, SECURITY_SESSION, ResponseSpec
from sidequest_common.models import Member
from sidequest_common.schemas import PvpBoards, PvpMatchDetail, PvpMatchPage


class PvpController(Controller):
    """``/api/pvp``: battleground match history and PvP boards from members' addon-recorded scoreboards."""

    path = "/api/pvp"
    tags = ["PvP"]
    security = SECURITY_SESSION
    dependencies = {"pvp_service": Provide(provide_pvp_service)}

    @get(
        "/matches",
        operation_id="ListPvpMatches",
        summary="List the battleground match history",
        description="Returns recorded battlegrounds, newest first, 25 to a page.",
        response_description="One page of the match history.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def list_matches(
        self,
        current_member: NamedDependency[Member],
        pvp_service: NamedDependency[PvpService],
        page: Annotated[int, QueryParameter(ge=1, description="The page, starting at 1.")] = 1,
    ) -> PvpMatchPage:
        del current_member
        return await pvp_service.list_matches(page)

    @get(
        "/matches/{match_id:uuid}",
        operation_id="GetPvpMatch",
        summary="Get one battleground's full scoreboard",
        description="Returns one recorded battleground with both sides' full scoreboard, highest honorable "
        "kills first.",
        response_description="The battleground's full scoreboard.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            404: ResponseSpec(None, description="No recorded battleground with this ID."),
        },
    )
    async def get_match(
        self,
        match_id: Annotated[UUID, Parameter(description="The battleground's ID.")],
        current_member: NamedDependency[Member],
        pvp_service: NamedDependency[PvpService],
    ) -> PvpMatchDetail:
        del current_member
        return await pvp_service.get_match(match_id)

    @get(
        "/boards",
        operation_id="GetPvpBoards",
        summary="Get the PvP boards",
        description="Returns totals over every recorded battleground for SideQuest characters, ten to a board.",
        response_description="The PvP boards.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def get_boards(
        self, current_member: NamedDependency[Member], pvp_service: NamedDependency[PvpService]
    ) -> PvpBoards:
        del current_member
        return await pvp_service.get_boards()
