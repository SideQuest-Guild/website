"""Hall of Heroes: ``/api/heroes``. Members only (any signed-in session, or the bot's ``X-API-Key``); else 401.

Gating is dependency-based (``member_or_bot``, registered app-wide in ``create_app``): declaring the parameter
resolves it, raising 401 before the handler body runs, like ``current_member``/``current_officer`` elsewhere.
"""

from typing import Annotated

from litestar import Controller, get
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import Parameter

from sidequest_api.domain.heroes.dependencies import provide_heroes_service
from sidequest_api.domain.heroes.services import HeroesService
from sidequest_api.lib.member_auth import provide_optional_member
from sidequest_common.schemas import HeroLeaderboard, HeroProfile


class HeroesController(Controller):
    """``/api/heroes``."""

    path = "/api/heroes"
    tags = ["Hall of Heroes"]
    dependencies = {
        "heroes_service": Provide(provide_heroes_service),
        "optional_member": Provide(provide_optional_member),
    }

    @get(
        "/",
        operation_id="GetHeroesLeaderboard",
        summary="Get the heroes leaderboard",
        description=(
            "Returns the season leaderboard, highest renown (EP) first. Requires a signed-in session or the "
            "bot's API key."
        ),
        response_description="The leaderboard for the given season.",
        responses={401: ResponseSpec(None, description="You are not signed in and did not send a valid API key.")},
    )
    async def get_leaderboard(
        self,
        heroes_service: NamedDependency[HeroesService],
        member_or_bot: NamedDependency[None],
        season: Annotated[str, Parameter(description="A season ID, `all`, or `month`.")] = "season-one",
    ) -> HeroLeaderboard:
        del member_or_bot
        return await heroes_service.get_leaderboard(season)

    @get(
        "/{member_id:int}",
        operation_id="GetHeroProfile",
        summary="Get a hero profile",
        description=(
            "Returns one member's full Hall of Heroes profile. Requires a signed-in session or the bot's API key."
        ),
        response_description="The member's Hall of Heroes profile.",
        responses={
            401: ResponseSpec(None, description="You are not signed in and did not send a valid API key."),
            404: ResponseSpec(None, description="No member with that ID."),
        },
    )
    async def get_profile(
        self,
        member_id: Annotated[int, Parameter(description="The member's ID.")],
        heroes_service: NamedDependency[HeroesService],
        member_or_bot: NamedDependency[None],
    ) -> HeroProfile:
        del member_or_bot
        return await heroes_service.get_profile(member_id)
