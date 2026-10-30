"""DI providers for the discord_signups domain.

``provide_discord_signup_target`` does both 404 checks (site guild, site account) once, so the controller's two
route handlers each take a single resolved dependency instead of repeating ``guild_id``/``event_id``/``discord_id``
path params plus two services.
"""

from dataclasses import dataclass
from uuid import UUID  # noqa: TC003 - a Litestar DI target, needs a real type

from advanced_alchemy.extensions.litestar.providers import create_service_provider
from litestar.di import NamedDependency  # noqa: TC002
from litestar.exceptions import NotFoundException
from litestar.params import FromPath  # noqa: TC002
from sqlalchemy import select

from sidequest_api.domain.events.services import EventSignupsService
from sidequest_common.models import Member
from sidequest_common.settings import WebSettings  # noqa: TC001 - a Litestar DI target, needs a real type

provide_event_signups_service = create_service_provider(EventSignupsService)


@dataclass(slots=True)
class DiscordSignupTarget:
    """A resolved event id + site member for one bot-key by-discord sign-up request."""

    event_id: UUID
    member: Member
    event_signups_service: EventSignupsService


async def provide_discord_signup_target(
    guild_id: FromPath[int],
    event_id: FromPath[UUID],
    discord_id: FromPath[int],
    event_signups_service: NamedDependency[EventSignupsService],
    web_settings: NamedDependency[WebSettings],
) -> DiscordSignupTarget:
    """404s for any ``guild_id`` other than the site guild, or a ``discord_id`` with no site account."""
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)
    session = event_signups_service.repository.session
    member = (await session.execute(select(Member).where(Member.discord_id == discord_id))).scalar_one_or_none()
    if member is None:
        msg = f"No member with Discord id {discord_id}"
        raise NotFoundException(msg)
    return DiscordSignupTarget(event_id=event_id, member=member, event_signups_service=event_signups_service)
