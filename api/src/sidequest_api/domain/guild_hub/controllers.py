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
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter, QueryParameter

from sidequest_api.domain.guild_hub.dependencies import provide_guild_hub_service
from sidequest_api.domain.guild_hub.services import GuildHubService
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION, GuildIdPath
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
    dependencies = {"guild_hub_service": Provide(provide_guild_hub_service)}

    @get(
        "/roster",
        operation_id="GetGuildRoster",
        tags=["Guild hub"],
        security=SECURITY_SESSION,
        summary="Get the guild roster",
        description="Returns the current roster. Alts are grouped under their linked member.",
        response_description="The current roster.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def get_roster(
        self, current_member: NamedDependency[Member], guild_hub_service: NamedDependency[GuildHubService]
    ) -> GuildRoster:
        del current_member
        return await guild_hub_service.get_roster()

    @get(
        "/crafters",
        operation_id="GetGuildCrafters",
        tags=["Guild hub"],
        security=SECURITY_SESSION,
        summary="Search guild crafters",
        description="Returns characters that know a recipe matching the search term or profession.",
        response_description="Characters matching the search.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def get_crafters(
        self,
        current_member: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
        q: Annotated[str | None, Parameter(description="A recipe or item name to search for.")] = None,
        profession: Annotated[str | None, Parameter(description="A profession to filter by.")] = None,
    ) -> GuildCrafters:
        del current_member
        return await guild_hub_service.get_crafters(q=q, profession=profession)

    @get(
        "/news",
        operation_id="GetGuildNews",
        tags=["Guild news"],
        summary="List guild news",
        description="Returns the guild news feed, newest first.",
        response_description="The guild's news feed.",
    )
    async def get_news(
        self,
        guild_hub_service: NamedDependency[GuildHubService],
        limit: Annotated[
            int, QueryParameter(ge=1, le=MAX_NEWS_LIMIT, description="The maximum number of items to return.")
        ] = DEFAULT_NEWS_LIMIT,
    ) -> GuildNewsPage:
        return await guild_hub_service.get_news(limit=limit)

    @get(
        "/bank",
        operation_id="GetGuildBank",
        tags=["Guild hub"],
        security=SECURITY_SESSION,
        summary="Get the guild bank log",
        description="Returns guild bank log rows, newest first, with 30-day totals.",
        response_description="The guild bank log.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def get_bank(
        self,
        current_member: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
        limit: Annotated[
            int, QueryParameter(ge=1, le=MAX_BANK_LIMIT, description="The maximum number of rows to return.")
        ] = DEFAULT_BANK_LIMIT,
        before: Annotated[
            datetime | None, QueryParameter(description="Only return rows logged before this timestamp.")
        ] = None,
    ) -> GuildBankPage:
        del current_member
        return await guild_hub_service.get_bank(limit=limit, before=before)

    @get(
        "/announcements",
        operation_id="GetGuildAnnouncements",
        tags=["Guild news"],
        summary="List guild announcements",
        description="Returns the last 20 announcements, from the game or the site.",
        response_description="The guild's recent announcements.",
    )
    async def get_announcements(self, guild_hub_service: NamedDependency[GuildHubService]) -> GuildAnnouncementsPage:
        return await guild_hub_service.get_announcements()

    @post(
        "/announcements",
        operation_id="CreateGuildAnnouncement",
        status_code=201,
        tags=["Guild hub admin"],
        security=SECURITY_SESSION,
        summary="Post a guild announcement",
        description="Creates a site-made announcement.",
        response_description="The new announcement.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def create_announcement(
        self,
        data: JSONBody[GuildAnnouncementCreate],
        current_officer: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
    ) -> GuildAnnouncementRow:
        return await guild_hub_service.create_announcement(data, current_officer)


class EpgpRecruitsController(Controller):
    """``/api/epgp/recruits``: recruiting candidates and officer votes (officer-only)."""

    path = "/api/epgp/recruits"
    tags = ["EPGP recruits"]
    security = SECURITY_SESSION
    dependencies = {"guild_hub_service": Provide(provide_guild_hub_service)}

    @get(
        "/",
        operation_id="ListEpgpRecruits",
        summary="List EPGP recruits",
        description="Returns every recruiting candidate, newest first.",
        response_description="The recruiting candidates.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def list_recruits(
        self, current_officer: NamedDependency[Member], guild_hub_service: NamedDependency[GuildHubService]
    ) -> EpgpRecruitList:
        del current_officer
        return await guild_hub_service.list_recruits()

    @put(
        "/{recruit_id:uuid}",
        operation_id="UpdateEpgpRecruit",
        summary="Update an EPGP recruit",
        description="Updates a recruit's status, note, or checklist. Only the fields present are changed.",
        response_description="The recruit's updated record.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="No recruit has this ID."),
        },
    )
    async def update_recruit(
        self,
        recruit_id: Annotated[UUID, Parameter(description="The recruit's ID.")],
        data: JSONBody[EpgpRecruitUpdate],
        current_officer: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
    ) -> EpgpRecruitRow:
        del current_officer
        return await guild_hub_service.update_recruit(recruit_id, data)

    @post(
        "/{recruit_id:uuid}/votes",
        operation_id="CreateEpgpRecruitVote",
        summary="Vote on an EPGP recruit",
        description="Adds or replaces the signed-in officer's vote on a recruit.",
        response_description="The recruit's updated record.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="No recruit has this ID."),
        },
    )
    async def add_vote(
        self,
        recruit_id: Annotated[UUID, Parameter(description="The recruit's ID.")],
        data: JSONBody[EpgpRecruitVoteCreate],
        current_officer: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
    ) -> EpgpRecruitRow:
        return await guild_hub_service.add_recruit_vote(recruit_id, data, current_officer)


class EpgpMemberNotesController(Controller):
    """``/api/epgp/member-notes``: officer notes about members/characters (officer-only, read-only on the site)."""

    path = "/api/epgp/member-notes"
    tags = ["Member notes"]
    security = SECURITY_SESSION
    dependencies = {"guild_hub_service": Provide(provide_guild_hub_service)}

    @get(
        "/",
        operation_id="ListEpgpMemberNotes",
        summary="List officer notes",
        description="Returns officer notes about members and characters, optionally filtered to one member.",
        response_description="The officer notes.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def list_notes(
        self,
        current_officer: NamedDependency[Member],
        guild_hub_service: NamedDependency[GuildHubService],
        member_id: Annotated[int | None, Parameter(description="Only return notes about this member.")] = None,
    ) -> EpgpMemberNoteList:
        del current_officer
        return await guild_hub_service.list_member_notes(member_id=member_id)


class GuildAnnouncementsBotController(Controller):
    """``/api/guilds/{guild_id}/announcements``: the bot's pending-announcement poll, bot-key only.

    404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``badges``/``member_links``).
    """

    path = "/announcements"
    tags = ["Guild announcements"]
    dependencies = {"guild_hub_service": Provide(provide_guild_hub_service)}

    @get(
        "/pending",
        operation_id="GetPendingAnnouncements",
        summary="List pending guild announcements",
        description=(
            "Returns Discord-queued announcements not yet posted, oldest first. Returns 404 for any guild_id "
            "other than the SideQuest server."
        ),
        response_description="The pending announcements.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server.")},
    )
    async def get_pending(
        self,
        guild_id: GuildIdPath,
        guild_hub_service: NamedDependency[GuildHubService],
        web_settings: NamedDependency[WebSettings],
    ) -> PendingAnnouncementsPage:
        _require_site_guild(guild_id, web_settings)
        return await guild_hub_service.list_pending_announcements()

    @post(
        "/{announcement_id:uuid}/posted",
        operation_id="MarkAnnouncementPosted",
        status_code=200,
        summary="Mark a guild announcement as posted",
        description=(
            "Records that an announcement posted to Discord with the given message ID. Returns 404 for any "
            "guild_id other than the SideQuest server, or an unknown announcement_id."
        ),
        response_description="The announcement's posted state.",
        responses={
            404: ResponseSpec(
                None,
                description="This guild_id is not the SideQuest server, or the announcement does not exist.",
            )
        },
    )
    async def mark_posted(
        self,
        guild_id: GuildIdPath,
        announcement_id: Annotated[UUID, Parameter(description="The announcement's ID.")],
        data: JSONBody[AnnouncementPosted],
        guild_hub_service: NamedDependency[GuildHubService],
        web_settings: NamedDependency[WebSettings],
    ) -> AnnouncementPostedResult:
        _require_site_guild(guild_id, web_settings)
        return await guild_hub_service.mark_announcement_posted(announcement_id, data.message_id)
