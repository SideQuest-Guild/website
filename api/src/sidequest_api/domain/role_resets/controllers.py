"""Discord role-reset outbox, bot-key only. ``/api/guilds/{guild_id}/role-resets``.

Written by ``MembersService.delete_account`` when a member deletes their site account: the bot strips every
Discord role it can manage from them (gate role excepted, since ``link_roles`` re-grants it the moment they're
unlinked) and acks. 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as
``event_sync``/``discord_live``/``member_links``).
"""

from typing import Annotated
from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import Parameter

from sidequest_api.domain.role_resets.dependencies import provide_role_resets_service
from sidequest_api.domain.role_resets.services import MemberRoleResetsService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import RoleResetCandidate
from sidequest_common.settings import WebSettings

_NOT_SITE_GUILD = ResponseSpec(None, description="This guild_id is not the SideQuest server.")


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class RoleResetsController(Controller):
    """``/api/guilds/{guild_id}/role-resets``: Discord role resets owed after a site account deletion."""

    path = "/role-resets"
    tags = ["Role resets"]
    dependencies = {"role_resets_service": Provide(provide_role_resets_service)}

    @get(
        "/",
        operation_id="ListRoleResets",
        summary="List pending role resets",
        description=(
            "Returns pending Discord role resets, oldest first, capped at 50. Returns 404 for any guild_id "
            "other than the SideQuest server."
        ),
        response_description="The pending role resets.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def list_role_resets(
        self,
        guild_id: GuildIdPath,
        role_resets_service: NamedDependency[MemberRoleResetsService],
        web_settings: NamedDependency[WebSettings],
    ) -> list[RoleResetCandidate]:
        _require_site_guild(guild_id, web_settings)
        return [
            RoleResetCandidate(id=reset.id, discord_id=reset.discord_id, requested_at=reset.requested_at)
            for reset in await role_resets_service.list_pending()
        ]

    @post(
        "/{reset_id:uuid}/ack",
        operation_id="AckRoleReset",
        status_code=204,
        summary="Acknowledge a role reset",
        description=(
            "Confirms the bot stripped this member's roles, or found them no longer in the guild. Returns 404 "
            "for any guild_id other than the SideQuest server, or for an unknown reset_id."
        ),
        response_description="The role reset was acknowledged.",
        responses={
            404: ResponseSpec(
                None, description="This guild_id is not the SideQuest server, or no such role reset exists."
            )
        },
    )
    async def ack_role_reset(
        self,
        guild_id: GuildIdPath,
        reset_id: Annotated[UUID, Parameter(description="The role reset's ID.")],
        role_resets_service: NamedDependency[MemberRoleResetsService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        reset = await role_resets_service.get_for_bot_action(reset_id)
        await role_resets_service.ack(reset)
