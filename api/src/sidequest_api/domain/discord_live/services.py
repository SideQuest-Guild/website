"""Upserts the guild's live-status report and reads it back, treating stale/missing reports as empty."""

from datetime import UTC, datetime

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService

from sidequest_common.models import DiscordLiveStatus
from sidequest_common.schemas import DiscordLive, DiscordLiveReport, VoiceChannelCount

LIVE_STALE_AFTER = 180
"""Seconds since the bot's last report after which the public endpoint reports empty counts (bot down)."""


class DiscordLiveRepository(SQLAlchemyAsyncRepository[DiscordLiveStatus]):
    """DiscordLiveStatus persistence."""

    model_type = DiscordLiveStatus


class DiscordLiveService(SQLAlchemyAsyncRepositoryService[DiscordLiveStatus]):
    """Stores the one live-status row per guild and reports it back, empty if stale or missing."""

    repository_type = DiscordLiveRepository
    match_fields = ["guild_id"]

    async def upsert_report(self, guild_id: int, report: DiscordLiveReport) -> DiscordLiveStatus:
        """Replace the guild's stored report and set ``reported_at`` to now."""
        voice = [item.model_dump() for item in report.voice]
        existing = await self.get_one_or_none(guild_id=guild_id)
        if existing is None:
            try:
                return await self.create(
                    DiscordLiveStatus(
                        guild_id=guild_id,
                        online=report.online,
                        members=report.members,
                        voice=voice,
                        reported_at=datetime.now(UTC),
                    ),
                    auto_commit=True,
                )
            except IntegrityError:
                # Another request created it between our read and insert. The failed flush poisons the session's
                # transaction, so roll back before reading the winner's row.
                await self.repository.session.rollback()
                existing = await self.get_one(guild_id=guild_id)
        existing.online = report.online
        existing.members = report.members
        existing.voice = voice
        existing.reported_at = datetime.now(UTC)
        return await self.update(existing, auto_commit=True)

    async def get_live(self, guild_id: int) -> DiscordLive:
        """The guild's live status, or empty counts if there's no row or the report is stale."""
        status = await self.get_one_or_none(guild_id=guild_id)
        if status is None:
            return DiscordLive(online=None, members=None, voice=[], reported_at=None)
        age = datetime.now(UTC) - status.reported_at
        if age.total_seconds() > LIVE_STALE_AFTER:
            return DiscordLive(online=None, members=None, voice=[], reported_at=status.reported_at)
        return DiscordLive(
            online=status.online,
            members=status.members,
            voice=[VoiceChannelCount.model_validate(item) for item in status.voice],
            reported_at=status.reported_at,
        )
