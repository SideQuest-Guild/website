"""DI providers for the weekly_board domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider

from sidequest_api.domain.weekly_board.services import WeeklyBoardService

provide_weekly_board_service = create_service_provider(WeeklyBoardService)
