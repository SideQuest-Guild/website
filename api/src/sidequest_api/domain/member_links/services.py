"""Member link status reporting for the bot's role sync."""

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService

from sidequest_common.models import Member


class MemberLinksRepository(SQLAlchemyAsyncRepository[Member]):
    """Member persistence for link-status reporting."""

    model_type = Member


class MemberLinksService(SQLAlchemyAsyncRepositoryService[Member]):
    """Reports every signed-in member's Battle.net link status."""

    repository_type = MemberLinksRepository

    async def list_links(self) -> list[Member]:
        """Every member who has signed in (one row exists per Discord user who has completed OAuth)."""
        return list(await self.get_many())
