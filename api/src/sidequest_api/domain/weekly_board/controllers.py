"""This week's scheduled events, bot-key only. ``/api/guilds/{guild_id}/weekly-board/events``.

Every route 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``event_sync``/
``discord_live``). Scoped to a date range (not just "upcoming") so the bot's Monday-morning post can bound itself
to exactly one week, and includes ``discord_thread_id`` (not in the public ``EventSummary``) so the post can link
each event's forum thread.
"""

from datetime import datetime

from litestar import Controller, get
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, FromQuery

from sidequest_api.domain.weekly_board.dependencies import provide_weekly_board_service
from sidequest_api.domain.weekly_board.services import WeeklyBoardService
from sidequest_common.schemas import WeeklyBoardEvent
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class WeeklyBoardController(Controller):
    """``/api/guilds/{guild_id}/weekly-board/events``: scheduled events starting within ``[start, end)``."""

    path = "/weekly-board"
    tags = ["Weekly Board"]
    dependencies = {"weekly_board_service": Provide(provide_weekly_board_service)}

    @get("/events", operation_id="ListWeeklyBoardEvents")
    async def list_events(
        self,
        guild_id: FromPath[int],
        start: FromQuery[datetime],
        end: FromQuery[datetime],
        weekly_board_service: NamedDependency[WeeklyBoardService],
        web_settings: NamedDependency[WebSettings],
    ) -> list[WeeklyBoardEvent]:
        """Scheduled events starting in ``[start, end)``, soonest first, with their forum thread id if any."""
        _require_site_guild(guild_id, web_settings)
        events = await weekly_board_service.list_week_events(start, end)
        return [WeeklyBoardEvent.model_validate(event) for event in events]
