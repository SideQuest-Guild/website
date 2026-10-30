"""Hall of Heroes: ``/api/heroes``. Members only (any signed-in session, or the bot's ``X-API-Key``); else 401.

Gating is dependency-based (``member_or_bot``, registered app-wide in ``create_app``): declaring the parameter
resolves it, raising 401 before the handler body runs, like ``current_member``/``current_officer`` elsewhere.
"""

from litestar import Controller, get
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, FromQuery

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

    @get("/", operation_id="GetHeroesLeaderboard")
    async def get_leaderboard(
        self,
        heroes_service: NamedDependency[HeroesService],
        member_or_bot: NamedDependency[None],
        season: FromQuery[str] = "season-one",
    ) -> HeroLeaderboard:
        """Highest EP first for ``season`` (a season id, ``"all"``, or ``"month"``)."""
        del member_or_bot
        return await heroes_service.get_leaderboard(season)

    @get("/{member_id:int}", operation_id="GetHeroProfile")
    async def get_profile(
        self,
        member_id: FromPath[int],
        heroes_service: NamedDependency[HeroesService],
        member_or_bot: NamedDependency[None],
    ) -> HeroProfile:
        """One member's full Hall of Heroes profile. 404 if there's no such member."""
        del member_or_bot
        return await heroes_service.get_profile(member_id)
