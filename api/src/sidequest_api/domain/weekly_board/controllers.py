"""This week's scheduled events, bot-key only. ``/api/guilds/{guild_id}/weekly-board/events``.

Every route 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``event_sync``/
``discord_live``). Scoped to a date range (not just "upcoming") so the bot's Monday-morning post can bound itself
to exactly one week, and includes ``discord_thread_id`` (not in the public ``EventSummary``) so the post can link
each event's forum thread.
"""

from datetime import datetime
from typing import Annotated

from litestar import Controller, get
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import Parameter

from sidequest_api.domain.weekly_board.dependencies import provide_weekly_board_service
from sidequest_api.domain.weekly_board.services import WeeklyBoardService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import WeeklyBoardEvent
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class WeeklyBoardController(Controller):
    """``/api/guilds/{guild_id}/weekly-board/events``: scheduled events starting within ``[start, end)``."""

    path = "/weekly-board"
    tags = ["Weekly board"]
    dependencies = {"weekly_board_service": Provide(provide_weekly_board_service)}

    @get(
        "/events",
        operation_id="ListWeeklyBoardEvents",
        summary="List this week's scheduled events",
        description=(
            "Returns scheduled events starting in the given date range, soonest first, with each event's forum "
            "thread ID if it has one. Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The events in the date range.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server.")},
    )
    async def list_events(
        self,
        guild_id: GuildIdPath,
        start: Annotated[datetime, Parameter(description="The start of the date range, inclusive.")],
        end: Annotated[datetime, Parameter(description="The end of the date range, exclusive.")],
        weekly_board_service: NamedDependency[WeeklyBoardService],
        web_settings: NamedDependency[WebSettings],
    ) -> list[WeeklyBoardEvent]:
        _require_site_guild(guild_id, web_settings)
        events = await weekly_board_service.list_week_events(start, end)
        return [WeeklyBoardEvent.model_validate(event) for event in events]
