"""Guild event <-> Discord scheduled event sync endpoints, bot-key only. ``/api/guilds/{guild_id}/event-sync``.

Guild events are single-guild: every route 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (the bot
treats 404 as "this guild isn't the site guild" and stops syncing it for the process lifetime).
"""

from typing import Annotated
from uuid import UUID

from litestar import Controller, delete, get, post, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.event_sync.dependencies import provide_event_sync_service
from sidequest_api.domain.event_sync.services import EventSyncService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import (
    ActivityAck,
    DiscordEventReconcile,
    DiscordEventState,
    DiscordInterestReport,
    DiscordPushAck,
    DiscordSyncPending,
)
from sidequest_common.settings import WebSettings

_NOT_SITE_GUILD = ResponseSpec(None, description="This guild_id is not the SideQuest server.")


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class EventSyncController(Controller):
    """``/api/guilds/{guild_id}/event-sync``: the bot pulls desired Discord state and reports Discord state back."""

    path = "/event-sync"
    tags = ["Event sync"]
    dependencies = {"event_sync_service": Provide(provide_event_sync_service)}

    @get(
        "/",
        operation_id="ListPendingEventSync",
        summary="List pending Discord event syncs",
        description=(
            "Returns every event push and tombstone the bot should apply to Discord now. "
            "Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The pending pushes and tombstones.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def list_pending(
        self,
        guild_id: GuildIdPath,
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> DiscordSyncPending:
        _require_site_guild(guild_id, web_settings)
        return await event_sync_service.list_pending(web_settings.BASE_URL, guild_id)

    @post(
        "/{event_id:uuid}/ack",
        operation_id="AckEventSync",
        status_code=204,
        summary="Acknowledge an event sync push",
        description=(
            "Confirms the bot applied the given push hash to this event's Discord event. "
            "Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The push was acknowledged.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def ack(
        self,
        guild_id: GuildIdPath,
        event_id: Annotated[UUID, Parameter(description="The site event's ID.")],
        data: JSONBody[DiscordPushAck],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.ack(event_id, data)

    @post(
        "/events",
        operation_id="ReportDiscordEvent",
        status_code=204,
        summary="Report a Discord scheduled event",
        description=(
            "Reports that one Discord scheduled event was created or updated. "
            "Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The event state was applied.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def report_event(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[DiscordEventState],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.apply_event_state(data)

    @delete(
        "/events/{event_id:int}",
        operation_id="ReportDeletedDiscordEvent",
        summary="Report a deleted Discord scheduled event",
        description=(
            "Reports that a Discord scheduled event was deleted. "
            "Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The deletion was recorded.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def report_deleted_event(
        self,
        guild_id: GuildIdPath,
        event_id: Annotated[int, Parameter(description="The Discord scheduled event's ID.")],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.handle_deleted_event(event_id)

    @delete(
        "/tombstones/{event_id:int}",
        operation_id="ClearEventSyncTombstone",
        summary="Clear an event sync tombstone",
        description=(
            "Drops the tombstone after the bot deleted this event in Discord. "
            "Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The tombstone was cleared.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def clear_tombstone(
        self,
        guild_id: GuildIdPath,
        event_id: Annotated[int, Parameter(description="The Discord scheduled event's ID.")],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.delete_tombstone(event_id)

    @put(
        "/interest/{discord_event_id:int}",
        operation_id="ReportEventInterest",
        status_code=204,
        summary="Report Discord event interest",
        description=(
            "Replaces the interested-user set for the guild event linked to a Discord scheduled event. "
            "Does nothing if no guild event is linked. Returns 404 for any guild_id other than the "
            "SideQuest server."
        ),
        response_description="The interest list was replaced.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def report_interest(
        self,
        guild_id: GuildIdPath,
        discord_event_id: Annotated[int, Parameter(description="The Discord scheduled event's ID.")],
        data: JSONBody[DiscordInterestReport],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.report_interest(discord_event_id, data.user_ids)

    @post(
        "/activity/ack",
        operation_id="AckEventActivity",
        status_code=204,
        summary="Acknowledge posted sign-up activity",
        description=(
            "Confirms the bot posted these sign-up activity rows in their event's forum thread. "
            "Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The activity rows were acknowledged.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def ack_activity(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[ActivityAck],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.ack_activity(data.ids)

    @post(
        "/reconcile",
        operation_id="ReconcileEventSync",
        status_code=204,
        summary="Reconcile Discord scheduled events",
        description=(
            "Reconciles deletions and stale tombstones against every scheduled event currently in the guild. "
            "Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The reconciliation ran.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def reconcile(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[DiscordEventReconcile],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.reconcile(data)
