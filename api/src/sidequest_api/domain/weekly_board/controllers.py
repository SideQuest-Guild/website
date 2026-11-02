"""This week's scheduled events and their Discord cards, bot-key only. ``/api/guilds/{guild_id}/weekly-board``.

Every route 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``event_sync``/
``discord_live``). Scoped to a date range (not just "upcoming") so the bot's Monday-morning post can bound itself
to exactly one week, and includes ``discord_thread_id`` (not in the public ``EventSummary``) so each card can link
its forum thread. The bot then records each card's message so the event sync keeps its sign-up lists current.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from litestar import Controller, get, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.weekly_board.dependencies import provide_weekly_board_service
from sidequest_api.domain.weekly_board.services import WeeklyBoardService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import WeeklyBoardEvent, WeeklyBoardMessage
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class WeeklyBoardController(Controller):
    """``/api/guilds/{guild_id}/weekly-board``: the week's scheduled events, and the card posted for each."""

    path = "/weekly-board"
    tags = ["Weekly board"]
    dependencies = {"weekly_board_service": Provide(provide_weekly_board_service)}

    @get(
        "/events",
        operation_id="ListWeeklyBoardEvents",
        summary="List this week's scheduled events",
        description=(
            "Returns scheduled events starting in the given date range, soonest first, with each event's forum "
            "thread ID if it has one and every sign-up in sign-up order. Returns 404 for any guild_id other than "
            "the SideQuest server."
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
        return await weekly_board_service.list_week_events(start, end)

    @put(
        "/events/{event_id:uuid}/message",
        operation_id="SetWeeklyBoardMessage",
        status_code=204,
        summary="Record an event's weekly board card",
        description=(
            "Records the Discord message the bot posted as this event's weekly board card, so later sign-up "
            "changes reach it through the event sync. Returns 404 for any guild_id other than the SideQuest "
            "server, or if the event doesn't exist."
        ),
        response_description="The card was recorded.",
        responses={404: ResponseSpec(None, description="Not the SideQuest server, or no such event.")},
    )
    async def set_message(
        self,
        guild_id: GuildIdPath,
        event_id: Annotated[UUID, Parameter(description="The site event's ID.")],
        data: JSONBody[WeeklyBoardMessage],
        weekly_board_service: NamedDependency[WeeklyBoardService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await weekly_board_service.set_board_message(event_id, data)
