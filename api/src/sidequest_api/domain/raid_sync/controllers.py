"""Raid <-> Discord scheduled event sync endpoints, bot-key only. ``/api/guilds/{guild_id}/raid-sync``.

Raids are single-guild: every route 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (the bot treats
404 as "this guild isn't the site guild" and stops syncing it for the process lifetime).
"""

from uuid import UUID

from litestar import Controller, delete, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, JSONBody

from sidequest_api.domain.raid_sync.dependencies import provide_raid_sync_service
from sidequest_api.domain.raid_sync.services import RaidSyncService
from sidequest_common.schemas import DiscordEventReconcile, DiscordEventState, DiscordPushAck, DiscordSyncPending
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class RaidSyncController(Controller):
    """``/api/guilds/{guild_id}/raid-sync``: the bot pulls desired Discord state and reports Discord state back."""

    path = "/raid-sync"
    tags = ["Raid Sync"]
    dependencies = {"raid_sync_service": Provide(provide_raid_sync_service)}

    @get("/", operation_id="ListPendingRaidSync")
    async def list_pending(
        self,
        guild_id: FromPath[int],
        raid_sync_service: NamedDependency[RaidSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> DiscordSyncPending:
        """Every raid push and tombstone the bot should apply to Discord now."""
        _require_site_guild(guild_id, web_settings)
        return await raid_sync_service.list_pending(web_settings.BASE_URL)

    @post("/{raid_id:uuid}/ack", operation_id="AckRaidSync", status_code=204)
    async def ack(
        self,
        guild_id: FromPath[int],
        raid_id: FromPath[UUID],
        data: JSONBody[DiscordPushAck],
        raid_sync_service: NamedDependency[RaidSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """The bot applied ``data.push_hash`` to this raid's Discord event."""
        _require_site_guild(guild_id, web_settings)
        await raid_sync_service.ack(raid_id, data)

    @post("/events", operation_id="ReportDiscordEvent", status_code=204)
    async def report_event(
        self,
        guild_id: FromPath[int],
        data: JSONBody[DiscordEventState],
        raid_sync_service: NamedDependency[RaidSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """One Discord scheduled event was created or updated."""
        _require_site_guild(guild_id, web_settings)
        await raid_sync_service.apply_event_state(data)

    @delete("/events/{event_id:int}", operation_id="ReportDeletedDiscordEvent")
    async def report_deleted_event(
        self,
        guild_id: FromPath[int],
        event_id: FromPath[int],
        raid_sync_service: NamedDependency[RaidSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """A Discord scheduled event was deleted."""
        _require_site_guild(guild_id, web_settings)
        await raid_sync_service.handle_deleted_event(event_id)

    @delete("/tombstones/{event_id:int}", operation_id="ClearRaidSyncTombstone")
    async def clear_tombstone(
        self,
        guild_id: FromPath[int],
        event_id: FromPath[int],
        raid_sync_service: NamedDependency[RaidSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """The bot deleted this event in Discord; drop the tombstone."""
        _require_site_guild(guild_id, web_settings)
        await raid_sync_service.delete_tombstone(event_id)

    @post("/reconcile", operation_id="ReconcileRaidSync", status_code=204)
    async def reconcile(
        self,
        guild_id: FromPath[int],
        data: JSONBody[DiscordEventReconcile],
        raid_sync_service: NamedDependency[RaidSyncService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """Every scheduled event currently in the guild: reconciles deletions and stale tombstones."""
        _require_site_guild(guild_id, web_settings)
        await raid_sync_service.reconcile(data)
