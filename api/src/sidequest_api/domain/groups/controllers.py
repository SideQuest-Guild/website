"""Group voice channels (LFG).

``GroupVoiceController`` (``/api/guilds/{guild_id}/groups``) is bot-key only: every route 404s for any ``guild_id``
other than ``WebSettings.GUILD_ID``, same rule as ``AttendanceVoiceController``/``DiscordLiveController``.
``GroupStatsController`` (``/api/groups``) mixes officer-gated stats/session routes (``current_officer``, session
auth) with the public leaderboard route, like ``AttendanceController`` mixes officer and GM routes under ``/api``.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from litestar import Controller, get, patch, post, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter, QueryParameter

from sidequest_api.domain.groups.dependencies import provide_groups_service
from sidequest_api.domain.groups.services import GroupsService
from sidequest_api.lib.openapi import NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION, GuildIdPath
from sidequest_common.models import Member
from sidequest_common.schemas import (
    GroupLeaderboard,
    GroupPresenceReport,
    GroupSessionClose,
    GroupSessionCreate,
    GroupSessionDetail,
    GroupSessionSchema,
    GroupSessionSummary,
    GroupSessionUpdate,
    GroupStats,
    GroupTranscriptPurge,
)
from sidequest_common.settings import WebSettings

_NOT_THIS_GUILD = ResponseSpec(None, description="This guild_id is not the SideQuest server.")
_NOT_THIS_GUILD_OR_SESSION = ResponseSpec(
    None, description="This guild_id is not the SideQuest server, or the session does not exist."
)

DEFAULT_SESSIONS_LIMIT = 50
MAX_SESSIONS_LIMIT = 200
DEFAULT_STATS_DAYS = 30
MAX_STATS_DAYS = 365


def _require_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class GroupVoiceController(Controller):
    """``/api/guilds/{guild_id}/groups``: the bot's group voice channel session lifecycle."""

    path = "/groups"
    tags = ["Group voice"]
    dependencies = {"groups_service": Provide(provide_groups_service)}

    @post(
        "/",
        operation_id="CreateGroupSession",
        status_code=201,
        summary="Create a group session",
        description=(
            "Records a group voice channel the bot just created. Returns 404 for any guild_id other than the "
            "SideQuest server. Returns 409 if the channel already has a session."
        ),
        response_description="The created group session.",
        responses={
            404: _NOT_THIS_GUILD,
            409: ResponseSpec(None, description="This channel already has a group session."),
        },
    )
    async def create_session(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[GroupSessionCreate],
        groups_service: NamedDependency[GroupsService],
        web_settings: NamedDependency[WebSettings],
    ) -> GroupSessionSchema:
        _require_guild(guild_id, web_settings)
        return await groups_service.create_session(data)

    @get(
        "/open",
        operation_id="ListOpenGroupSessions",
        summary="List open group sessions",
        description=(
            "Returns every session that hasn't ended, oldest first, with presence so far, so a restarted bot can "
            "resume counting. Returns 404 for any guild_id other than the SideQuest server."
        ),
        response_description="The open group sessions.",
        responses={404: _NOT_THIS_GUILD},
    )
    async def list_open_sessions(
        self,
        guild_id: GuildIdPath,
        groups_service: NamedDependency[GroupsService],
        web_settings: NamedDependency[WebSettings],
    ) -> list[GroupSessionSchema]:
        _require_guild(guild_id, web_settings)
        return await groups_service.list_open()

    @get(
        "/{session_id:uuid}",
        operation_id="GetGroupSession",
        summary="Get a group session",
        description=(
            "Returns one group session's settings and presence so far. Returns 404 for any guild_id other than "
            "the SideQuest server, or an unknown session."
        ),
        response_description="The group session.",
        responses={404: _NOT_THIS_GUILD_OR_SESSION},
    )
    async def get_session(
        self,
        guild_id: GuildIdPath,
        session_id: Annotated[UUID, Parameter(description="The session's ID.")],
        groups_service: NamedDependency[GroupsService],
        web_settings: NamedDependency[WebSettings],
    ) -> GroupSessionSchema:
        _require_guild(guild_id, web_settings)
        return await groups_service.get_session(session_id)

    @patch(
        "/{session_id:uuid}",
        operation_id="UpdateGroupSession",
        summary="Update a group session",
        description=(
            "Changes only the fields present in the request body; `channel_name: null` is ignored (it is never "
            "cleared). Returns 404 for any guild_id other than the SideQuest server, or an unknown session."
        ),
        response_description="The updated group session.",
        responses={404: _NOT_THIS_GUILD_OR_SESSION},
    )
    async def update_session(
        self,
        guild_id: GuildIdPath,
        session_id: Annotated[UUID, Parameter(description="The session's ID.")],
        data: JSONBody[GroupSessionUpdate],
        groups_service: NamedDependency[GroupsService],
        web_settings: NamedDependency[WebSettings],
    ) -> GroupSessionSchema:
        _require_guild(guild_id, web_settings)
        return await groups_service.update_session(session_id, data)

    @put(
        "/{session_id:uuid}/presence",
        operation_id="ReportGroupPresence",
        status_code=204,
        summary="Report group presence",
        description=(
            "Raises the session's stored peak size, grouped minutes, and per-member/pair minutes to the reported "
            "max. Never lowers a stored total. Returns 404 for any guild_id other than the SideQuest server, or "
            "an unknown session."
        ),
        response_description="The presence report was applied.",
        responses={404: _NOT_THIS_GUILD_OR_SESSION},
    )
    async def report_presence(
        self,
        guild_id: GuildIdPath,
        session_id: Annotated[UUID, Parameter(description="The session's ID.")],
        data: JSONBody[GroupPresenceReport],
        groups_service: NamedDependency[GroupsService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_guild(guild_id, web_settings)
        await groups_service.upsert_presence(session_id, data)

    @post(
        "/{session_id:uuid}/close",
        operation_id="CloseGroupSession",
        status_code=204,
        summary="Close a group session",
        description=(
            "Ends a session: sets `ended_at`, `end_reason`, merges final presence, and stores the transcript if "
            "non-empty. Idempotent: closing an already-closed session only merges presence (keeps the first "
            "`ended_at`/`end_reason`/transcript). Also purges any transcripts past the retention window. Returns "
            "404 for any guild_id other than the SideQuest server, or an unknown session."
        ),
        response_description="The session was closed.",
        responses={404: _NOT_THIS_GUILD_OR_SESSION},
    )
    async def close_session(
        self,
        guild_id: GuildIdPath,
        session_id: Annotated[UUID, Parameter(description="The session's ID.")],
        data: JSONBody[GroupSessionClose],
        groups_service: NamedDependency[GroupsService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_guild(guild_id, web_settings)
        await groups_service.close_session(session_id, data)

    @post(
        "/purge",
        operation_id="PurgeGroupTranscripts",
        status_code=200,
        summary="Purge expired group transcripts",
        description=(
            "Deletes transcripts of sessions that ended more than the retention window ago. Returns 404 for any "
            "guild_id other than the SideQuest server."
        ),
        response_description="How many transcripts were deleted.",
        responses={404: _NOT_THIS_GUILD},
    )
    async def purge_transcripts(
        self,
        guild_id: GuildIdPath,
        groups_service: NamedDependency[GroupsService],
        web_settings: NamedDependency[WebSettings],
    ) -> GroupTranscriptPurge:
        _require_guild(guild_id, web_settings)
        return await groups_service.purge_transcripts()


class GroupStatsController(Controller):
    """``/api/groups``: officer stats and session browsing, plus the public leaderboard."""

    path = "/api/groups"
    dependencies = {"groups_service": Provide(provide_groups_service)}

    @get(
        "/stats",
        operation_id="GetGroupStats",
        tags=["Group stats"],
        security=SECURITY_SESSION,
        summary="Get group stats",
        description="Returns who groups, with whom, and what, over the last `days` days. An officer must be signed in.",
        response_description="The group stats for the window.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def get_stats(
        self,
        current_officer: NamedDependency[Member],
        groups_service: NamedDependency[GroupsService],
        days: Annotated[
            int, QueryParameter(ge=1, le=MAX_STATS_DAYS, description="The size of the window, in days.")
        ] = DEFAULT_STATS_DAYS,
    ) -> GroupStats:
        del current_officer
        return await groups_service.stats(days)

    @get(
        "/sessions",
        operation_id="ListGroupSessions",
        tags=["Group stats"],
        security=SECURITY_SESSION,
        summary="List group sessions",
        description="Returns open and closed group sessions, newest first. An officer must be signed in.",
        response_description="The group sessions.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def list_sessions(
        self,
        current_officer: NamedDependency[Member],
        groups_service: NamedDependency[GroupsService],
        limit: Annotated[
            int, QueryParameter(ge=1, le=MAX_SESSIONS_LIMIT, description="The maximum number of sessions to return.")
        ] = DEFAULT_SESSIONS_LIMIT,
        before: Annotated[
            datetime | None, QueryParameter(description="Only return sessions that started before this timestamp.")
        ] = None,
    ) -> list[GroupSessionSummary]:
        del current_officer
        return await groups_service.list_sessions(limit=limit, before=before)

    @get(
        "/sessions/{session_id:uuid}",
        operation_id="GetGroupSessionDetail",
        tags=["Group stats"],
        security=SECURITY_SESSION,
        summary="Get a group session's detail",
        description=(
            "Returns one session with who was in it and its chat, if still kept. `transcript` is null once purged "
            "or past the retention window. An officer must be signed in."
        ),
        response_description="The group session's detail.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER, 404: ResponseSpec(None, description="Unknown session.")},
    )
    async def get_session_detail(
        self,
        session_id: Annotated[UUID, Parameter(description="The session's ID.")],
        current_officer: NamedDependency[Member],
        groups_service: NamedDependency[GroupsService],
    ) -> GroupSessionDetail:
        del current_officer
        return await groups_service.get_session_detail(session_id)

    @get(
        "/leaderboard",
        operation_id="GetGroupLeaderboard",
        tags=["Group leaderboard"],
        summary="Get the group leaderboard",
        description=(
            "Returns the top 10 members by counted groups joined in the last 30 days, and the top 10 all time. "
            "Only members with a site account appear. Anyone may read it."
        ),
        response_description="The group leaderboard.",
    )
    async def get_leaderboard(self, groups_service: NamedDependency[GroupsService]) -> GroupLeaderboard:
        return await groups_service.leaderboard()
