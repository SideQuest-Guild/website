"""Event sign-up lookup/upsert by Discord id, bot-key only.

``GET/PUT /api/guilds/{guild_id}/events/{event_id}/signups/by-discord/{discord_id}``. Every route 404s for any
``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``event_sync``/``discord_live``), and for a
``discord_id`` with no site account (the bot's Going/Maybe/Can't buttons tell that visitor to sign in first).

``PUT`` reuses ``EventSignupsService.upsert_signup`` so a Discord sign-up writes the exact same activity row and
forum comment as a site sign-up; it 409s the same way if the event isn't scheduled.
"""

from litestar import Controller, get, put
from litestar.di import NamedDependency, Provide
from litestar.params import JSONBody

from sidequest_api.domain.discord_signups.dependencies import (
    DiscordSignupTarget,
    provide_discord_signup_target,
    provide_event_signups_service,
)
from sidequest_common.schemas import Signup, SignupByDiscord, SignupUpsert


class DiscordSignupsController(Controller):
    """``/api/guilds/{guild_id}/events/{event_id}/signups/by-discord/{discord_id}``."""

    path = ""
    tags = ["Discord Signups"]
    dependencies = {
        "event_signups_service": Provide(provide_event_signups_service),
        "target": Provide(provide_discord_signup_target),
    }

    @get("/events/{event_id:uuid}/signups/by-discord/{discord_id:int}", operation_id="GetEventSignupByDiscord")
    async def get_event_signup_by_discord(self, target: NamedDependency[DiscordSignupTarget]) -> SignupByDiscord:
        """The member's current signup for this event, plus their most recent character/class/role.

        404 if ``discord_id`` has never signed in on the site, or if ``event_id`` doesn't exist.
        """
        return await target.event_signups_service.get_by_discord(target.event_id, target.member)

    @put("/events/{event_id:uuid}/signups/by-discord/{discord_id:int}", operation_id="UpsertEventSignupByDiscord")
    async def upsert_event_signup_by_discord(
        self, data: JSONBody[SignupUpsert], target: NamedDependency[DiscordSignupTarget]
    ) -> Signup:
        """Create or replace the member's signup for this event, identified by Discord id.

        404 if ``discord_id`` has never signed in on the site. 409 if the event isn't scheduled. 400 if the
        event's kind is ``raid``/``dungeon`` and ``character``/``class``/``role`` aren't all present, unless
        ``status`` is ``absent``.
        """
        return await target.event_signups_service.upsert_signup(target.event_id, target.member, data)
