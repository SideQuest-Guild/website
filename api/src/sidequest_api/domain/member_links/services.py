"""Member link status reporting for the bot's role sync."""

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService

from sidequest_common.models import Member


class MemberLinksRepository(SQLAlchemyAsyncRepository[Member]):
    """Member persistence for link-status reporting."""

    model_type = Member


class MemberLinksService(SQLAlchemyAsyncRepositoryService[Member]):
    """Reports every known member's sign-in and Battle.net link status."""

    repository_type = MemberLinksRepository

    async def list_links(self) -> list[Member]:
        """Every known member: signed in, or confirmed from Discord without ever signing in."""
        return list(await self.get_many())
