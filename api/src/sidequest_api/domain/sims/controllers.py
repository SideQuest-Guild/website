"""Sim job endpoints: the bot queues a gear-swap sim and polls its status.

Queueing validates the whole request (character, items, spec) before answering: a bad request 400s right away
instead of queueing a job that only fails once the runner picks it up. ``wowsims_dir`` is a app-level dependency
(``create_app``), the same checkout the background runner uses.
"""

from http import HTTPStatus
from pathlib import Path
from typing import Annotated
from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter
from wow import AsyncClient

from sidequest_api.domain.characters.dependencies import provide_characters_service
from sidequest_api.domain.characters.services import CharactersService
from sidequest_api.domain.sims.dependencies import provide_sims_service
from sidequest_api.domain.sims.services import SimsService
from sidequest_api.lib.game_data import provide_game_data
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import SimJobSchema, SimRequest

_NOT_FOUND = ResponseSpec(None, description="No sim job with this id.")


class SimsController(Controller):
    """``/api/guilds/{guild_id:int}/sims``."""

    path = "/sims"
    tags = ["Sims"]
    dependencies = {
        "sims_service": Provide(provide_sims_service),
        "characters_service": Provide(provide_characters_service),
        "game_data": Provide(provide_game_data),
    }

    @post(
        "/",
        operation_id="QueueSim",
        status_code=HTTPStatus.ACCEPTED,
        summary="Queue a sim",
        description=(
            "Validates and queues a gear-swap sim for a character, resolved through the character's stored "
            "Battle.net sheet (fetched fresh if stale). Runs one at a time per web pod through the wowsims/forever "
            "CLI; poll Get a sim job for its result. 400s for an unknown character, an unknown or ambiguous item "
            "(with up to 5 suggestions), an unsupported class/spec, or an item that doesn't fit its slot. 429s if "
            "`requested_by` already has 3 jobs queued or running."
        ),
        response_description="The queued job, with its position.",
    )
    async def queue_sim(
        self,
        *,
        guild_id: GuildIdPath,  # noqa: ARG002 - the site runs one guild; this documents/validates the path only
        data: JSONBody[SimRequest],
        sims_service: NamedDependency[SimsService],
        characters_service: NamedDependency[CharactersService],
        game_data: NamedDependency[AsyncClient],
        wowsims_dir: NamedDependency[Path],
    ) -> SimJobSchema:
        return await sims_service.queue(
            data, characters_service=characters_service, game_data=game_data, wowsims_dir=wowsims_dir
        )

    @get(
        "/{job_id:uuid}",
        operation_id="GetSimJob",
        summary="Get a sim job",
        description="Returns one sim job's status, queue position (while queued), and result (once done).",
        response_description="The sim job.",
        responses={404: _NOT_FOUND},
    )
    async def get_sim_job(
        self,
        guild_id: GuildIdPath,  # noqa: ARG002 - the site runs one guild; this documents/validates the path only
        job_id: Annotated[UUID, Parameter(description="The job's id, from Queue a sim.")],
        sims_service: NamedDependency[SimsService],
    ) -> SimJobSchema:
        return await sims_service.get(job_id)
