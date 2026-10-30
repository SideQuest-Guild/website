"""Guild hub v2 endpoints.

``GuildHubController`` (``/api/guild``): roster/crafters (member), news/announcements (public read), and
site-made announcements (officer). ``EpgpRecruitsController``/``EpgpMemberNotesController`` sit under
``/api/epgp`` alongside the EPGP domain (officer-only, same guards as the rest of EPGP admin).
``GuildAnnouncementsBotController`` is mounted in ``guild_controllers`` (``X-API-Key``, see
``sidequest_api.domain.__init__``): the bot polls pending Discord announcements and marks them posted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from litestar import Controller, get, post, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, FromQuery, JSONBody, QueryParameter

from sidequest_api.domain.guild_hub.dependencies import provide_guild_hub_service
from sidequest_api.domain.guild_hub.services import GuildHubService
from sidequest_common.models import Member
from sidequest_common.schemas import (
    AnnouncementPosted,
    AnnouncementPostedResult,
    EpgpMemberNoteList,
    EpgpRecruitList,
    EpgpRecruitRow,
    EpgpRecruitUpdate,
    EpgpRecruitVoteCreate,
    GuildAnnouncementCreate,
    GuildAnnouncementRow,
    GuildAnnouncementsPage,
    GuildBankPage,
    GuildCrafters,
    GuildNewsPage,
    GuildRoster,
    PendingAnnouncementsPage,
)
from sidequest_common.settings import WebSettings

DEFAULT_NEWS_LIMIT = 30
MAX_NEWS_LIMIT = 60
DEFAULT_BANK_LIMIT = 50
MAX_BANK_LIMIT = 200


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class GuildHubController(Controller):
    """``/api/guild``: roster, crafters, news, bank, and announcements."""

    path = "/api/guild"
    tags = ["Guild Hub"]
    dependencies = {"guild_hub_service": Provide(provide_guild_hub_service)}

    @get("/roster", operation_id="GetGuildRoster")
    async def get_roster(
        self, current_member: NamedDependency[Member], guild_hub_service: NamedDependency[GuildHubService]
    ) -> GuildRoster:
        """The current roster, alts grouped under their linked member (member). 401/403 non-member."""
        del current_member
        return await guild_hub_service.get_roster()

    @get("/crafters", operation_id="GetGuildCrafters")
    async def get_crafters(
        self,
        current_member: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
        q: FromQuery[str | None] = None,
        profession: FromQuery[str | None] = None,
    ) -> GuildCrafters:
        """Characters that know a recipe matching ``q``/``profession`` (member). 401/403 non-member."""
        del current_member
        return await guild_hub_service.get_crafters(q=q, profession=profession)

    @get("/news", operation_id="GetGuildNews")
    async def get_news(
        self,
        guild_hub_service: NamedDependency[GuildHubService],
        limit: Annotated[int, QueryParameter(ge=1, le=MAX_NEWS_LIMIT)] = DEFAULT_NEWS_LIMIT,
    ) -> GuildNewsPage:
        """Guild news feed, newest first (public)."""
        return await guild_hub_service.get_news(limit=limit)

    @get("/bank", operation_id="GetGuildBank")
    async def get_bank(
        self,
        current_member: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
        limit: Annotated[int, QueryParameter(ge=1, le=MAX_BANK_LIMIT)] = DEFAULT_BANK_LIMIT,
        before: FromQuery[datetime | None] = None,
    ) -> GuildBankPage:
        """Guild bank log rows newest first, with 30-day totals (member). 401/403 non-member."""
        del current_member
        return await guild_hub_service.get_bank(limit=limit, before=before)

    @get("/announcements", operation_id="GetGuildAnnouncements")
    async def get_announcements(self, guild_hub_service: NamedDependency[GuildHubService]) -> GuildAnnouncementsPage:
        """The last 20 announcements, game- or site-sourced (public)."""
        return await guild_hub_service.get_announcements()

    @post("/announcements", operation_id="CreateGuildAnnouncement", status_code=201)
    async def create_announcement(
        self,
        data: JSONBody[GuildAnnouncementCreate],
        current_officer: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
    ) -> GuildAnnouncementRow:
        """A site-made announcement (officer). 401/403 non-officer."""
        return await guild_hub_service.create_announcement(data, current_officer)


class EpgpRecruitsController(Controller):
    """``/api/epgp/recruits``: recruiting candidates and officer votes (officer-only)."""

    path = "/api/epgp/recruits"
    tags = ["EPGP"]
    dependencies = {"guild_hub_service": Provide(provide_guild_hub_service)}

    @get("/", operation_id="ListEpgpRecruits")
    async def list_recruits(
        self, current_officer: NamedDependency[Member], guild_hub_service: NamedDependency[GuildHubService]
    ) -> EpgpRecruitList:
        """Every recruiting candidate, newest first (officer). 401/403 non-officer."""
        del current_officer
        return await guild_hub_service.list_recruits()

    @put("/{recruit_id:uuid}", operation_id="UpdateEpgpRecruit")
    async def update_recruit(
        self,
        recruit_id: FromPath[UUID],
        data: JSONBody[EpgpRecruitUpdate],
        current_officer: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
    ) -> EpgpRecruitRow:
        """Update status/note/checklist (officer). 401/403 non-officer, 404 unknown recruit."""
        del current_officer
        return await guild_hub_service.update_recruit(recruit_id, data)

    @post("/{recruit_id:uuid}/votes", operation_id="CreateEpgpRecruitVote")
    async def add_vote(
        self,
        recruit_id: FromPath[UUID],
        data: JSONBody[EpgpRecruitVoteCreate],
        current_officer: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
    ) -> EpgpRecruitRow:
        """Upsert the signed-in officer's vote (officer). 401/403 non-officer, 404 unknown recruit."""
        return await guild_hub_service.add_recruit_vote(recruit_id, data, current_officer)


class EpgpMemberNotesController(Controller):
    """``/api/epgp/member-notes``: officer notes about members/characters (officer-only, read-only on the site)."""

    path = "/api/epgp/member-notes"
    tags = ["EPGP"]
    dependencies = {"guild_hub_service": Provide(provide_guild_hub_service)}

    @get("/", operation_id="ListEpgpMemberNotes")
    async def list_notes(
        self,
        current_officer: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
        member_id: FromQuery[int | None] = None,
    ) -> EpgpMemberNoteList:
        """Officer notes, optionally filtered to one member (officer). 401/403 non-officer."""
        del current_officer
        return await guild_hub_service.list_member_notes(member_id=member_id)


class GuildAnnouncementsBotController(Controller):
    """``/api/guilds/{guild_id}/announcements``: the bot's pending-announcement poll, bot-key only.

    404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``badges``/``member_links``).
    """

    path = "/announcements"
    tags = ["Guild Hub"]
    dependencies = {"guild_hub_service": Provide(provide_guild_hub_service)}

    @get("/pending", operation_id="GetPendingAnnouncements")
    async def get_pending(
        self,
        guild_id: FromPath[int],
        guild_hub_service: NamedDependency[GuildHubService],
        web_settings: NamedDependency[WebSettings],
    ) -> PendingAnnouncementsPage:
        """Discord-queued announcements not yet posted, oldest first."""
        _require_site_guild(guild_id, web_settings)
        return await guild_hub_service.list_pending_announcements()

    @post("/{announcement_id:uuid}/posted", operation_id="MarkAnnouncementPosted", status_code=200)
    async def mark_posted(
        self,
        guild_id: FromPath[int],
        announcement_id: FromPath[UUID],
        data: JSONBody[AnnouncementPosted],
        guild_hub_service: NamedDependency[GuildHubService],
        web_settings: NamedDependency[WebSettings],
    ) -> AnnouncementPostedResult:
        """Record that ``announcement_id`` posted as ``message_id``. 404 unknown announcement."""
        _require_site_guild(guild_id, web_settings)
        return await guild_hub_service.mark_announcement_posted(announcement_id, data.message_id)
