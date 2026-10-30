"""Event sign-up lookup/upsert by Discord id, bot-key only.

``GET/PUT /api/guilds/{guild_id}/events/{event_id}/signups/by-discord/{discord_id}``. Every route 404s for any
``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``event_sync``/``discord_live``), and for a
``discord_id`` with no site account (the bot's Going/Maybe/Can't buttons tell that visitor to sign in first).

``PUT`` reuses ``EventSignupsService.upsert_signup`` so a Discord sign-up writes the exact same activity row and
forum comment as a site sign-up; it 409s the same way if the event isn't scheduled.
"""

from litestar import Controller, get, put
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody

from sidequest_api.domain.discord_signups.dependencies import (
    DiscordSignupTarget,
    provide_discord_signup_target,
    provide_event_signups_service,
)
from sidequest_common.schemas import Signup, SignupByDiscord, SignupUpsert

_NOT_FOUND = ResponseSpec(
    None,
    description="This guild_id is not the SideQuest server, the event is unknown, or discord_id never signed in.",
)


class DiscordSignupsController(Controller):
    """``/api/guilds/{guild_id}/events/{event_id}/signups/by-discord/{discord_id}``."""

    path = ""
    tags = ["Discord signups"]
    dependencies = {
        "event_signups_service": Provide(provide_event_signups_service),
        "target": Provide(provide_discord_signup_target),
    }

    @get(
        "/events/{event_id:uuid}/signups/by-discord/{discord_id:int}",
        operation_id="GetEventSignupByDiscord",
        summary="Get a member's event signup by Discord ID",
        description=(
            "Returns the member's current signup for an event, plus their most recent character, class, and "
            "role. Returns 404 for any guild_id other than the SideQuest server, an unknown event, or a Discord "
            "ID with no site account."
        ),
        response_description="The member's signup for the event.",
        responses={404: _NOT_FOUND},
    )
    async def get_event_signup_by_discord(self, target: NamedDependency[DiscordSignupTarget]) -> SignupByDiscord:
        return await target.event_signups_service.get_by_discord(target.event_id, target.member)

    @put(
        "/events/{event_id:uuid}/signups/by-discord/{discord_id:int}",
        operation_id="UpsertEventSignupByDiscord",
        summary="Create or replace a member's event signup by Discord ID",
        description=(
            "Creates or replaces the member's signup for an event, identified by Discord ID. Returns 404 for "
            "any guild_id other than the SideQuest server, an unknown event, or a Discord ID with no site "
            "account. Returns 409 if the event is not scheduled. Returns 400 if the event's kind is raid or "
            "dungeon and character, class, or role are missing, unless status is absent."
        ),
        response_description="The created or updated signup.",
        responses={
            404: _NOT_FOUND,
            409: ResponseSpec(None, description="The event is not scheduled."),
            400: ResponseSpec(
                None,
                description="The event's kind is raid or dungeon and character, class, or role are missing.",
            ),
        },
    )
    async def upsert_event_signup_by_discord(
        self, data: JSONBody[SignupUpsert], target: NamedDependency[DiscordSignupTarget]
    ) -> Signup:
        return await target.event_signups_service.upsert_signup(target.event_id, target.member, data)
