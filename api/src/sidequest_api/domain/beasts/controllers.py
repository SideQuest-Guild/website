"""Tameable beast endpoints: public reference lookups from Battle.net, for hunters browsing pets to tame.

``GET /api/beasts/{id}`` and ``GET /api/beasts/families`` have no query string, so Cloudflare keeps them at the
edge (``EDGE_BEASTS_CACHE``); ``GET /api/beasts`` takes ``q``/``family_id``/``limit``, so it is never cached at the
edge, same as item search (``domain/items/controllers.py``). ``services.py`` also caches the whole catalog
in-process, since tameable beasts only change with a game patch.
"""

from typing import Annotated

from litestar import Controller, get
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.params import Parameter
from wow import AsyncClient

from sidequest_api.domain.beasts.services import get_beast, list_beasts, list_families
from sidequest_api.lib.game_data import provide_game_data
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_common.schemas import BeastFamilySchema, BeastSchema

_CREATURE_ID = Annotated[int, Parameter(description="The beast's Battle.net creature id.", gt=0)]
_LIMIT = Annotated[int | None, Parameter(description="At most this many beasts.", gt=0, le=1000)]

# Forever's tameable beasts change only with a game patch, same as other reference data: an hour at the edge, then
# stale while one fetch refreshes it.
EDGE_BEASTS_CACHE = ResponseHeader(name=EDGE_CACHE_HEADER, value="max-age=3600, stale-while-revalidate=86400")


class BeastsController(Controller):
    """``/api/beasts``: every tameable beast, searchable by name and family."""

    path = "/api/beasts"
    tags = ["Beasts"]
    dependencies = {"game_data": Provide(provide_game_data)}

    @get(
        "/",
        operation_id="ListBeasts",
        opt=SKIP_SESSION,
        summary="List tameable beasts",
        description=(
            "Returns every tameable beast: its family and display render, sorted by name. `q` keeps a "
            "case-insensitive substring of the name (a prefix match sorts first); `family_id` keeps one family; "
            "`limit` caps the result to its first entries, up to 1000. Answers 503 if Battle.net is not configured "
            "or did not answer."
        ),
        response_description="Tameable beasts, sorted by name.",
    )
    async def list_all(
        self,
        game_data: NamedDependency[AsyncClient],
        q: Annotated[
            str | None, Parameter(description="Case-insensitive name substring; a prefix match sorts first.")
        ] = None,
        family_id: Annotated[int | None, Parameter(description="Only beasts in this family.", gt=0)] = None,
        limit: _LIMIT = None,
    ) -> list[BeastSchema]:
        return await list_beasts(game_data, q=q, family_id=family_id, limit=limit)

    @get(
        "/families",
        operation_id="ListBeastFamilies",
        response_headers=[EDGE_BEASTS_CACHE],
        opt=SKIP_SESSION,
        summary="List beast families",
        description=(
            "Returns every beast family among tameable beasts, with how many tameable beasts belong to it, sorted "
            "by name. Answers 503 if Battle.net is not configured or did not answer."
        ),
        response_description="Beast families, sorted by name.",
    )
    async def list_families_route(self, game_data: NamedDependency[AsyncClient]) -> list[BeastFamilySchema]:
        return await list_families(game_data)

    @get(
        "/{creature_id:int}",
        operation_id="GetBeast",
        response_headers=[EDGE_BEASTS_CACHE],
        opt=SKIP_SESSION,
        summary="Get a tameable beast",
        description=(
            "Returns one tameable beast by its Battle.net creature id, from the same tameable-beast catalog "
            "`GET /api/beasts` lists. Answers 404 if that catalog has no such beast, 503 if Battle.net is not "
            "configured or did not answer."
        ),
        response_description="The tameable beast.",
    )
    async def get_one(self, game_data: NamedDependency[AsyncClient], creature_id: _CREATURE_ID) -> BeastSchema:
        return await get_beast(game_data, creature_id)
