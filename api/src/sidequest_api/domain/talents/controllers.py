"""Talent calculator endpoints: public trees and pinned builds, a member's own builds, officer pinning.

``GET /api/talents/{wow_class}`` has no query string, so Cloudflare may keep it at the edge; the in-process cache
in ``services.py`` covers the rest of the process's traffic.
"""

from typing import Annotated
from uuid import UUID

from litestar import Controller, delete, get, post, put
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter, QueryParameter
from wow import AsyncClient

from sidequest_api.domain.talents.dependencies import provide_talent_builds_service
from sidequest_api.domain.talents.services import TalentBuildsService
from sidequest_api.domain.talents.services import get_class_talents as fetch_class_talents
from sidequest_api.lib.game_data import provide_game_data
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import ClassTalents, TalentBuildCreate, TalentBuildPinUpdate, TalentBuildSchema, WowClass

_BUILD_ID = Annotated[UUID, Parameter(description="The talent build's ID.")]

# Classic talent trees never change outside a game patch: an hour at the edge, then stale while one fetch refreshes.
EDGE_TALENTS_CACHE = ResponseHeader(name=EDGE_CACHE_HEADER, value="max-age=3600, stale-while-revalidate=86400")


class TalentsController(Controller):
    """``/api/talents``: a class's three talent trees."""

    path = "/api/talents"
    tags = ["Talents"]
    dependencies = {"game_data": Provide(provide_game_data)}

    @get(
        "/{wow_class:str}",
        operation_id="GetClassTalents",
        response_headers=[EDGE_TALENTS_CACHE],
        opt=SKIP_SESSION,
        summary="Get a class's talent trees",
        description=(
            "Returns the class's three specialization talent trees from Battle.net: every node's position, ranks, "
            "the spell each rank grants and its prerequisite, plus the calculator's point cap and first level. "
            "Answers 503 if Battle.net is not configured or did not answer."
        ),
        response_description="The class's talent trees.",
    )
    async def get_class_talents(
        self,
        game_data: NamedDependency[AsyncClient],
        wow_class: Annotated[WowClass, Parameter(description="The class to get talent trees for.")],
    ) -> ClassTalents:
        return await fetch_class_talents(wow_class, game_data)


class TalentBuildsController(Controller):
    """``/api/talent-builds``: officer-pinned raid builds, and officer pinning."""

    path = "/api/talent-builds"
    dependencies = {"talent_builds_service": Provide(provide_talent_builds_service)}

    @get(
        "/",
        operation_id="ListPinnedTalentBuilds",
        tags=["Talents"],
        opt=SKIP_SESSION,
        summary="List a class's pinned talent builds",
        description="Returns the raid builds officers have pinned for the class, newest first. Anyone may read them.",
        response_description="The class's pinned builds.",
    )
    async def list_pinned(
        self,
        talent_builds_service: NamedDependency[TalentBuildsService],
        wow_class: Annotated[
            WowClass, QueryParameter(name="class", description="The class to list pinned builds for.")
        ],
    ) -> list[TalentBuildSchema]:
        return await talent_builds_service.list_pinned(wow_class)

    @put(
        "/{build_id:uuid}/pin",
        operation_id="PinTalentBuild",
        tags=["Talent build pins"],
        security=SECURITY_SESSION,
        summary="Pin or unpin a talent build",
        description=(
            "Marks a build as an officer-recommended raid build, or clears that mark. An officer must be signed in."
        ),
        response_description="The build, with its new pinned state.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER, 404: ResponseSpec(None, description="No such build.")},
    )
    async def set_pinned(
        self,
        build_id: _BUILD_ID,
        data: JSONBody[TalentBuildPinUpdate],
        current_officer: NamedDependency[Member],
        talent_builds_service: NamedDependency[TalentBuildsService],
    ) -> TalentBuildSchema:
        build = await talent_builds_service.set_pinned(build_id, pinned=data.pinned)
        await record_officer_audit(
            talent_builds_service.repository.session,
            actor=current_officer,
            action="talent_build.pin" if data.pinned else "talent_build.unpin",
            subject_type="talent_build",
            subject_id=str(build_id),
            summary=f"{'Pinned' if data.pinned else 'Unpinned'} {build.name} ({build.wow_class.value})",
        )
        return build


class MyTalentBuildsController(Controller):
    """``/api/me/talent-builds``: the signed-in member's own saved talent builds."""

    path = "/api/me/talent-builds"
    tags = ["My talent builds"]
    security = SECURITY_SESSION
    dependencies = {
        "talent_builds_service": Provide(provide_talent_builds_service),
        "game_data": Provide(provide_game_data),
    }

    @get(
        "/",
        operation_id="ListMyTalentBuilds",
        summary="List my talent builds",
        description="Returns every talent build the signed-in member has saved, across every class, newest first.",
        response_description="The member's saved builds.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def list_mine(
        self, current_member: NamedDependency[Member], talent_builds_service: NamedDependency[TalentBuildsService]
    ) -> list[TalentBuildSchema]:
        return await talent_builds_service.list_for_member(current_member)

    @post(
        "/",
        operation_id="SaveMyTalentBuild",
        summary="Save a talent build",
        description=(
            "Validates the build's talent code against the class's live trees (ranks, prerequisites, row gating "
            "and the point cap) and saves it. A member may hold at most 20 builds."
        ),
        response_description="The saved build.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            400: ResponseSpec(None, description="The talent code breaks one of the class's talent rules."),
            409: ResponseSpec(None, description="The member already holds 20 saved builds."),
        },
    )
    async def save_build(
        self,
        data: JSONBody[TalentBuildCreate],
        current_member: NamedDependency[Member],
        talent_builds_service: NamedDependency[TalentBuildsService],
        game_data: NamedDependency[AsyncClient],
    ) -> TalentBuildSchema:
        return await talent_builds_service.create_for_member(current_member, data, game_data)

    @delete(
        "/{build_id:uuid}",
        operation_id="DeleteMyTalentBuild",
        summary="Delete a talent build",
        description="Deletes one of the signed-in member's own saved builds.",
        response_description="The build is deleted.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER, 404: ResponseSpec(None, description="No such build.")},
    )
    async def delete_build(
        self,
        build_id: _BUILD_ID,
        current_member: NamedDependency[Member],
        talent_builds_service: NamedDependency[TalentBuildsService],
    ) -> None:
        await talent_builds_service.delete_own(current_member, build_id)
