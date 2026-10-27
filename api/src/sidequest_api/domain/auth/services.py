"""Discord OAuth2 login flow: exchange the code, fetch the profile, upsert the member."""

from typing import TYPE_CHECKING

from sidequest_api.lib.discord import DiscordOAuthError, exchange_code, fetch_current_user, fetch_guild_member

if TYPE_CHECKING:
    import httpx

    from sidequest_api.domain.members.services import MembersService
    from sidequest_common.models import Member
    from sidequest_common.settings import WebSettings


class AuthService:
    """Wraps the Discord OAuth token/user/guild-member exchange and member upsert for the login callback."""

    def __init__(
        self, discord_client: httpx.AsyncClient, members_service: MembersService, web_settings: WebSettings
    ) -> None:
        self._discord_client = discord_client
        self._members_service = members_service
        self._web_settings = web_settings

    async def complete_login(self, *, code: str) -> Member:
        """Exchange ``code`` for a token, fetch the Discord profile, and upsert the Member.

        Raises ``DiscordOAuthError`` if Discord isn't configured or any step of the exchange fails.
        """
        client_id = self._web_settings.DISCORD_CLIENT_ID
        client_secret = self._web_settings.DISCORD_CLIENT_SECRET
        if client_id is None or client_secret is None:
            msg = "Discord OAuth is not configured"
            not_configured = "oauth_not_configured"
            raise DiscordOAuthError(not_configured, msg)
        token = await exchange_code(
            self._discord_client,
            client_id=client_id,
            client_secret=client_secret.get_secret_value(),
            redirect_uri=self._redirect_uri(),
            code=code,
        )
        user = await fetch_current_user(self._discord_client, token)
        guild_id = self._web_settings.GUILD_ID
        guild_member = await fetch_guild_member(self._discord_client, token, guild_id)
        return await self._members_service.upsert_from_discord(user, guild_member)

    def _redirect_uri(self) -> str:
        return f"{self._web_settings.BASE_URL}/auth/discord/callback"
