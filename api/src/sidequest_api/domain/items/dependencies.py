"""DI providers for the items domain."""

from advanced_alchemy.extensions.litestar.providers import create_service_provider
from litestar.di import NamedDependency  # noqa: TC002 - provide_wishlist_service is a Litestar DI target
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002 - provide_wishlist_service is a Litestar DI target

from sidequest_api.domain.items.services import ItemsService
from sidequest_api.domain.items.wishlist import WishlistService

provide_items_service = create_service_provider(ItemsService)


async def provide_wishlist_service(db_session: NamedDependency[AsyncSession]) -> WishlistService:
    """A ``WishlistService`` bound to the request's session."""
    return WishlistService(db_session)
