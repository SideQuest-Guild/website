"""Moderation Cases endpoints."""

from typing import Annotated

from litestar import Controller, get, patch, post
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.cases.dependencies import provide_cases_service
from sidequest_api.domain.cases.services import CasesService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import ModCaseCreate, ModCaseSchema, ModCaseUpdate


class CasesController(Controller):
    """``/api/guilds/{guild_id:int}/cases``."""

    path = "/cases"
    tags = ["Moderation cases"]
    dependencies = {"cases_service": Provide(provide_cases_service)}

    @post(
        "/",
        operation_id="CreateCase",
        status_code=201,
        summary="Create a moderation case",
        description="Records a moderation action. The API assigns the case number.",
        response_description="The created case.",
        responses={409: ResponseSpec(None, description="Too many concurrent writers; could not assign a case number.")},
    )
    async def create_case(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[ModCaseCreate],
        cases_service: NamedDependency[CasesService],
    ) -> ModCaseSchema:
        case = await cases_service.create_case(guild_id, data)
        return ModCaseSchema.model_validate(case)

    @get(
        "/",
        operation_id="ListCases",
        summary="List moderation cases",
        description="Returns the guild's moderation cases, newest first. Pass user_id to filter to one member.",
        response_description="A page of moderation cases.",
    )
    async def list_cases(
        self,
        guild_id: GuildIdPath,
        cases_service: NamedDependency[CasesService],
        user_id: Annotated[int | None, Parameter(description="Only return cases for this Discord user ID.")] = None,
        limit: Annotated[int, Parameter(description="The maximum number of cases to return.", ge=1, le=100)] = 25,
        offset: Annotated[int, Parameter(description="The number of leading cases to skip.", ge=0)] = 0,
    ) -> list[ModCaseSchema]:
        cases = await cases_service.list_cases(guild_id, user_id=user_id, limit=limit, offset=offset)
        return [ModCaseSchema.model_validate(case) for case in cases]

    @get(
        "/{case_number:int}",
        operation_id="GetCase",
        summary="Get a moderation case",
        description="Returns one moderation case by its case number.",
        response_description="The case.",
        responses={404: ResponseSpec(None, description="No case with that number exists in the guild.")},
    )
    async def get_case(
        self,
        guild_id: GuildIdPath,
        case_number: Annotated[int, Parameter(description="The case's guild-scoped case number.")],
        cases_service: NamedDependency[CasesService],
    ) -> ModCaseSchema:
        case = await cases_service.get_case(guild_id, case_number)
        return ModCaseSchema.model_validate(case)

    @patch(
        "/{case_number:int}",
        operation_id="UpdateCase",
        summary="Update a moderation case",
        description="Edits a case. Currently only its reason can change.",
        response_description="The updated case.",
        responses={404: ResponseSpec(None, description="No case with that number exists in the guild.")},
    )
    async def update_case(
        self,
        guild_id: GuildIdPath,
        case_number: Annotated[int, Parameter(description="The case's guild-scoped case number.")],
        data: JSONBody[ModCaseUpdate],
        cases_service: NamedDependency[CasesService],
    ) -> ModCaseSchema:
        case = await cases_service.update_case(guild_id, case_number, data)
        return ModCaseSchema.model_validate(case)
