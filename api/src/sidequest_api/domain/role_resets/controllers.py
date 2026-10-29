"""Discord role-reset outbox, bot-key only. ``/api/guilds/{guild_id}/role-resets``.

Written by ``MembersService.delete_account`` when a member deletes their site account: the bot strips every
Discord role it can manage from them (gate role excepted, since ``link_roles`` re-grants it the moment they're
unlinked) and acks. 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as
``event_sync``/``discord_live``/``member_links``).
"""

from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath

from sidequest_api.domain.role_resets.dependencies import provide_role_resets_service
from sidequest_api.domain.role_resets.services import MemberRoleResetsService
from sidequest_common.schemas import RoleResetCandidate
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class RoleResetsController(Controller):
    """``/api/guilds/{guild_id}/role-resets``: Discord role resets owed after a site account deletion."""

    path = "/role-resets"
    tags = ["Role Resets"]
    dependencies = {"role_resets_service": Provide(provide_role_resets_service)}

    @get("/", operation_id="ListRoleResets")
    async def list_role_resets(
        self,
        guild_id: FromPath[int],
        role_resets_service: NamedDependency[MemberRoleResetsService],
        web_settings: NamedDependency[WebSettings],
    ) -> list[RoleResetCandidate]:
        """Pending role resets, oldest first, capped at 50."""
        _require_site_guild(guild_id, web_settings)
        return [
            RoleResetCandidate(id=reset.id, discord_id=reset.discord_id, requested_at=reset.requested_at)
            for reset in await role_resets_service.list_pending()
        ]

    @post("/{reset_id:uuid}/ack", operation_id="AckRoleReset", status_code=204)
    async def ack_role_reset(
        self,
        guild_id: FromPath[int],
        reset_id: FromPath[UUID],
        role_resets_service: NamedDependency[MemberRoleResetsService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        """The bot has stripped this member's roles (or found them no longer in the guild)."""
        _require_site_guild(guild_id, web_settings)
        reset = await role_resets_service.get_for_bot_action(reset_id)
        await role_resets_service.ack(reset)
