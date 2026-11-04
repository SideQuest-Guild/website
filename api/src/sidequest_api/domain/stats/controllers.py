"""Officer stats endpoint.

Gating is dependency-based (``current_officer``, registered app-wide in ``create_app``): declaring the parameter
resolves it, raising 401/403 before the handler body runs, like ``current_member``/``current_gm`` elsewhere.
"""

from typing import Annotated

from litestar import Controller, get
from litestar.di import NamedDependency, Provide
from litestar.params import QueryParameter

from sidequest_api.domain.stats.dependencies import provide_stats_service
from sidequest_api.domain.stats.services import StatsService
from sidequest_api.lib.openapi import NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import GuildStats, StatsRange


class StatsController(Controller):
    """``/api/stats``: guild-wide activity stats for officers."""

    path = "/api/stats"
    tags = ["Statistics"]
    security = SECURITY_SESSION
    dependencies = {"stats_service": Provide(provide_stats_service)}

    @get(
        "/",
        operation_id="GetStats",
        summary="Get guild stats",
        description=(
            "Returns guild-wide activity totals, trend, heatmap, leaderboards, and who's gone quiet, over the "
            "given window. An officer must be signed in."
        ),
        response_description="The guild's stats for the window.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def get_stats(
        self,
        current_officer: NamedDependency[Member],
        stats_service: NamedDependency[StatsService],
        stats_range: Annotated[
            StatsRange, QueryParameter(name="range", description="The stats window.")
        ] = StatsRange.SEVEN_DAYS,
    ) -> GuildStats:
        del current_officer
        return await stats_service.get_stats(stats_range)
