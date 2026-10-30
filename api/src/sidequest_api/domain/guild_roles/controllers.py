"""Discord role names, bot-key only, mounted at ``/api/guilds/{guild_id}/roles``.

Every route 404s for any ``guild_id`` other than ``WebSettings.GUILD_ID`` (same rule as ``discord_live``/
``event_sync``). The bot pushes the guild's full role set on its ``LiveStatusCog`` loop; ``@everyone`` is excluded
by the bot.
"""

from litestar import Controller, put
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody

from sidequest_api.domain.guild_roles.dependencies import provide_guild_roles_service
from sidequest_api.domain.guild_roles.services import GuildRolesService
from sidequest_api.lib.openapi import GuildIdPath
from sidequest_common.schemas import GuildRolesReplace
from sidequest_common.settings import WebSettings


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


class GuildRolesController(Controller):
    """``/api/guilds/{guild_id}/roles``: the bot reports the guild's full current role set."""

    path = "/roles"
    tags = ["Guild roles"]
    dependencies = {"guild_roles_service": Provide(provide_guild_roles_service)}

    @put(
        "/",
        operation_id="ReplaceGuildRoles",
        status_code=204,
        summary="Replace the guild's Discord roles",
        description=(
            "Replaces the guild's stored role set wholesale. Returns 404 for any guild_id other than the "
            "SideQuest server."
        ),
        response_description="The roles were replaced.",
        responses={404: ResponseSpec(None, description="This guild_id is not the SideQuest server.")},
    )
    async def replace_roles(
        self,
        guild_id: GuildIdPath,
        data: JSONBody[GuildRolesReplace],
        guild_roles_service: NamedDependency[GuildRolesService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await guild_roles_service.replace_roles(guild_id, data.roles)
