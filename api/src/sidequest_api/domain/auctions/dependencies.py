"""DI providers for the auctions domain.

``provide_auction_bot_member`` resolves the ``{guild_id}``/``{user_id}`` bot routes to the linked site ``Member``
in one place: 404 for any guild other than the site guild, or a Discord user id with no linked site account, the
same shape as ``DiscordSignupTarget``.
"""

from typing import Annotated

from litestar.di import NamedDependency  # noqa: TC002 - a Litestar DI target, needs a real type
from litestar.exceptions import NotFoundException
from litestar.params import Parameter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002 - a Litestar DI target, needs a real type

from sidequest_api.domain.auctions.services import AuctionsService
from sidequest_api.lib.openapi import GuildIdPath  # noqa: TC001 - a Litestar DI target, needs a real type
from sidequest_common.models import Member
from sidequest_common.settings import WebSettings  # noqa: TC001 - a Litestar DI target, needs a real type


async def provide_auctions_service(db_session: NamedDependency[AsyncSession]) -> AuctionsService:
    """An ``AuctionsService`` bound to the request's session."""
    return AuctionsService(db_session)


def require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    """404s for any ``guild_id`` other than the site guild (same rule as ``away``/``event_sync``)."""
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


async def provide_auction_bot_member(
    guild_id: GuildIdPath,
    user_id: Annotated[int, Parameter(description="The member's Discord user ID.")],
    db_session: NamedDependency[AsyncSession],
    web_settings: NamedDependency[WebSettings],
) -> Member:
    """The site member linked to ``user_id``. 404s for any guild other than the site guild, or an unlinked user."""
    require_site_guild(guild_id, web_settings)
    member = (await db_session.execute(select(Member).where(Member.discord_id == user_id))).scalar_one_or_none()
    if member is None:
        msg = f"Discord user {user_id} has not linked their Discord account on the site"
        raise NotFoundException(msg)
    return member
