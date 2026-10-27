"""Moderation Cases endpoints."""

from typing import Annotated

from litestar import Controller, get, patch, post
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, FromQuery, JSONBody, QueryParameter

from sidequest_api.domain.cases.dependencies import provide_cases_service
from sidequest_api.domain.cases.services import CasesService
from sidequest_common.schemas import ModCaseCreate, ModCaseSchema, ModCaseUpdate


class CasesController(Controller):
    """``/api/guilds/{guild_id:int}/cases``."""

    path = "/cases"
    tags = ["Moderation Cases"]
    dependencies = {"cases_service": Provide(provide_cases_service)}

    @post("/", operation_id="CreateCase", status_code=201)
    async def create_case(
        self,
        guild_id: FromPath[int],
        data: JSONBody[ModCaseCreate],
        cases_service: NamedDependency[CasesService],
    ) -> ModCaseSchema:
        """Record a moderation action; the API assigns the case number."""
        case = await cases_service.create_case(guild_id, data)
        return ModCaseSchema.model_validate(case)

    @get("/", operation_id="ListCases")
    async def list_cases(
        self,
        guild_id: FromPath[int],
        cases_service: NamedDependency[CasesService],
        user_id: FromQuery[int | None] = None,
        limit: Annotated[int, QueryParameter(ge=1, le=100)] = 25,
        offset: Annotated[int, QueryParameter(ge=0)] = 0,
    ) -> list[ModCaseSchema]:
        """Cases for the guild, newest first, optionally only for ``user_id``."""
        cases = await cases_service.list_cases(guild_id, user_id=user_id, limit=limit, offset=offset)
        return [ModCaseSchema.model_validate(case) for case in cases]

    @get("/{case_number:int}", operation_id="GetCase")
    async def get_case(
        self,
        guild_id: FromPath[int],
        case_number: FromPath[int],
        cases_service: NamedDependency[CasesService],
    ) -> ModCaseSchema:
        """One case. 404 if it doesn't exist."""
        case = await cases_service.get_case(guild_id, case_number)
        return ModCaseSchema.model_validate(case)

    @patch("/{case_number:int}", operation_id="UpdateCase")
    async def update_case(
        self,
        guild_id: FromPath[int],
        case_number: FromPath[int],
        data: JSONBody[ModCaseUpdate],
        cases_service: NamedDependency[CasesService],
    ) -> ModCaseSchema:
        """Edit a case (currently just its reason)."""
        case = await cases_service.update_case(guild_id, case_number, data)
        return ModCaseSchema.model_validate(case)
