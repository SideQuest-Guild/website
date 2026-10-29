"""Guild event <-> Discord scheduled event sync endpoints, bot-key only. ``/api/guilds/{guild_id}/event-sync``.

Guild events are single-guild: every route 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (the bot
treats 404 as "this guild isn't the site guild" and stops syncing it for the process lifetime).
"""

from uuid import UUID

from litestar import Controller, delete, get, post, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, JSONBody

from sidequest_api.domain.event_sync.dependencies import provide_event_sync_service
from sidequest_api.domain.event_sync.services import EventSyncService
from sidequest_common.schemas import (
    ActivityAck,
    DiscordEventReconcile,
    DiscordEventState,
    DiscordInterestReport,
    DiscordPushAck,
    DiscordSyncPending,
)
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class EventSyncController(Controller):
    """``/api/guilds/{guild_id}/event-sync``: the bot pulls desired Discord state and reports Discord state back."""

    path = "/event-sync"
    tags = ["Event Sync"]
    dependencies = {"event_sync_service": Provide(provide_event_sync_service)}

    @get("/", operation_id="ListPendingEventSync")
    async def list_pending(
        self,
        guild_id: FromPath[int],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> DiscordSyncPending:
        """Every event push and tombstone the bot should apply to Discord now."""
        _require_site_guild(guild_id, web_settings)
        return await event_sync_service.list_pending(web_settings.BASE_URL, guild_id)

    @post("/{event_id:uuid}/ack", operation_id="AckEventSync", status_code=204)
    async def ack(
        self,
        guild_id: FromPath[int],
        event_id: FromPath[UUID],
        data: JSONBody[DiscordPushAck],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """The bot applied ``data.push_hash`` to this event's Discord event."""
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.ack(event_id, data)

    @post("/events", operation_id="ReportDiscordEvent", status_code=204)
    async def report_event(
        self,
        guild_id: FromPath[int],
        data: JSONBody[DiscordEventState],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """One Discord scheduled event was created or updated."""
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.apply_event_state(data)

    @delete("/events/{event_id:int}", operation_id="ReportDeletedDiscordEvent")
    async def report_deleted_event(
        self,
        guild_id: FromPath[int],
        event_id: FromPath[int],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """A Discord scheduled event was deleted."""
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.handle_deleted_event(event_id)

    @delete("/tombstones/{event_id:int}", operation_id="ClearEventSyncTombstone")
    async def clear_tombstone(
        self,
        guild_id: FromPath[int],
        event_id: FromPath[int],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """The bot deleted this event in Discord; drop the tombstone."""
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.delete_tombstone(event_id)

    @put("/interest/{discord_event_id:int}", operation_id="ReportEventInterest", status_code=204)
    async def report_interest(
        self,
        guild_id: FromPath[int],
        discord_event_id: FromPath[int],
        data: JSONBody[DiscordInterestReport],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """Replace the interested-user set for the guild event linked to ``discord_event_id``; no-op if unlinked."""
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.report_interest(discord_event_id, data.user_ids)

    @post("/activity/ack", operation_id="AckEventActivity", status_code=204)
    async def ack_activity(
        self,
        guild_id: FromPath[int],
        data: JSONBody[ActivityAck],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """The bot posted these sign-up activity rows in their event's forum thread."""
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.ack_activity(data.ids)

    @post("/reconcile", operation_id="ReconcileEventSync", status_code=204)
    async def reconcile(
        self,
        guild_id: FromPath[int],
        data: JSONBody[DiscordEventReconcile],
        event_sync_service: NamedDependency[EventSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """Every scheduled event currently in the guild: reconciles deletions and stale tombstones."""
        _require_site_guild(guild_id, web_settings)
        await event_sync_service.reconcile(data)
