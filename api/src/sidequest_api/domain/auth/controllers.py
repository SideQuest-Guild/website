"""Discord OAuth2 login endpoints: redirect to Discord, handle the callback, and log out."""

import secrets
from typing import Annotated

import httpx
from litestar import Controller, Request, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import HTTPException
from litestar.params import FromQuery, QueryParameter
from litestar.response import Redirect
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE

from sidequest_api.domain.auth.services import AuthService
from sidequest_api.domain.members.dependencies import provide_members_service
from sidequest_api.domain.members.services import MembersService
from sidequest_api.lib.discord import DiscordOAuthError, build_authorize_url, provide_discord_client
from sidequest_api.lib.member_auth import safe_next_path
from sidequest_common.settings import WebSettings

DEFAULT_NEXT = "/account/"


def provide_auth_service(
    discord_client: NamedDependency[httpx.AsyncClient],
    members_service: NamedDependency[MembersService],
    web_settings: NamedDependency[WebSettings],
) -> AuthService:
    """Build the ``AuthService`` for this request from its already-provided dependencies."""
    return AuthService(discord_client, members_service, web_settings)


class AuthController(Controller):
    """``/auth``: Discord OAuth2 login, callback, and logout."""

    path = "/auth"
    tags = ["Auth"]
    dependencies = {
        "discord_client": Provide(provide_discord_client),
        "members_service": Provide(provide_members_service),
        "auth_service": Provide(provide_auth_service, sync_to_thread=False),
    }

    @get("/discord/login", operation_id="DiscordLogin")
    async def login(
        self,
        request: Request,
        web_settings: NamedDependency[WebSettings],
        next_target: Annotated[str | None, QueryParameter(name="next")] = None,
    ) -> Redirect:
        """Redirect to Discord's authorize screen. 503 if Discord OAuth isn't configured.

        ``next`` is only honored if it's a same-site path starting with a single ``/``; stored in the session
        and consumed by the callback.
        """
        client_id = web_settings.DISCORD_CLIENT_ID
        if client_id is None or web_settings.DISCORD_CLIENT_SECRET is None:
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail="Discord login is not configured")
        state = secrets.token_urlsafe(32)
        request.session["oauth_state"] = state
        safe_next = safe_next_path(next_target)
        if safe_next:
            request.session["oauth_next"] = safe_next
        else:
            request.session.pop("oauth_next", None)
        redirect_uri = f"{web_settings.BASE_URL}/auth/discord/callback"
        return Redirect(build_authorize_url(client_id=client_id, redirect_uri=redirect_uri, state=state))

    @get("/discord/callback", operation_id="DiscordCallback", include_in_schema=False)
    async def callback(
        self,
        request: Request,
        auth_service: NamedDependency[AuthService],
        code: FromQuery[str | None] = None,
        oauth_state: Annotated[str | None, QueryParameter(name="state")] = None,
    ) -> Redirect:
        """Verify ``state``, exchange ``code``, upsert the member, and redirect to ``next`` (or ``/account/``).

        On any failure, redirects to ``/account/?error=<short-code>`` instead.
        """
        expected_state = request.session.pop("oauth_state", None)
        next_path = request.session.pop("oauth_next", None) or DEFAULT_NEXT
        if not code or not oauth_state or not expected_state or not secrets.compare_digest(oauth_state, expected_state):
            return Redirect(f"{DEFAULT_NEXT}?error=state")
        try:
            member = await auth_service.complete_login(code=code)
        except DiscordOAuthError as exc:
            return Redirect(f"{DEFAULT_NEXT}?error={exc.code}")
        request.set_session({"member_id": member.id})
        return Redirect(next_path)

    @post("/logout", operation_id="Logout", status_code=204)
    async def logout(self, request: Request) -> None:
        """Clear the session cookie."""
        request.clear_session()
