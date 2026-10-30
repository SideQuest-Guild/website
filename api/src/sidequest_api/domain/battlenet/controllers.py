"""Link a signed-in member's Battle.net account: redirect to Blizzard, handle the callback, unlink.

These are browser navigations from ``/account/``, so failures redirect back there with ``?error=<code>``
rather than returning JSON. Linking always attaches to the member signed in with Discord; Battle.net is never a
standalone login.
"""

import secrets
from typing import Annotated

import httpx
from litestar import Controller, Request, get, post
from litestar.di import NamedDependency, Provide
from litestar.params import QueryParameter
from litestar.response import Redirect

from sidequest_api.domain.members.dependencies import provide_members_service
from sidequest_api.domain.members.services import MembersService
from sidequest_api.lib.battlenet import (
    BattleNetOAuthError,
    build_authorize_url,
    exchange_code,
    fetch_userinfo,
    provide_battlenet_client,
)
from sidequest_api.lib.member_auth import provide_optional_member, safe_next_path
from sidequest_api.lib.openapi import NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_common.models import Member
from sidequest_common.settings import WebSettings

ACCOUNT_PATH = "/account/"
_STATE_KEY = "battlenet_state"
_NEXT_KEY = "battlenet_next"


def _back(error: str) -> Redirect:
    return Redirect(f"{ACCOUNT_PATH}?error={error}")


class BattleNetController(Controller):
    """``/auth/battlenet``: link and unlink a Battle.net account."""

    path = "/auth/battlenet"
    tags = ["Battle.net account"]
    dependencies = {
        "battlenet_client": Provide(provide_battlenet_client),
        "members_service": Provide(provide_members_service),
        "optional_member": Provide(provide_optional_member),
    }

    @get(
        "/link",
        operation_id="BattleNetLink",
        summary="Start a Battle.net link",
        description=(
            "Redirects the browser to Battle.net's authorize screen so the signed-in member can link their "
            "Battle.net account. Redirects back to the account page with an error code if the member is not "
            "signed in with Discord or Battle.net is not configured."
        ),
        response_description="Redirect to Battle.net's authorize screen.",
    )
    async def link(
        self,
        request: Request,
        web_settings: NamedDependency[WebSettings],
        optional_member: NamedDependency[Member | None],
        next_target: Annotated[
            str | None, QueryParameter(name="next", description="Where to send the browser after linking.")
        ] = None,
    ) -> Redirect:
        if optional_member is None:
            return _back("signin_first")
        client_id = web_settings.BATTLENET_CLIENT_ID
        if client_id is None or not web_settings.battlenet_configured:
            return _back("battlenet_not_configured")
        state = secrets.token_urlsafe(32)
        request.session[_STATE_KEY] = state
        request.session[_NEXT_KEY] = safe_next_path(next_target) or ACCOUNT_PATH
        redirect_uri = f"{web_settings.BASE_URL}/auth/battlenet/callback"
        return Redirect(build_authorize_url(client_id=client_id, redirect_uri=redirect_uri, state=state))

    @get("/callback", operation_id="BattleNetCallback", include_in_schema=False)
    async def callback(
        self,
        *,
        request: Request,
        web_settings: NamedDependency[WebSettings],
        optional_member: NamedDependency[Member | None],
        battlenet_client: NamedDependency[httpx.AsyncClient],
        members_service: NamedDependency[MembersService],
        code: Annotated[str | None, QueryParameter()] = None,
        oauth_state: Annotated[str | None, QueryParameter(name="state")] = None,
        oauth_error: Annotated[str | None, QueryParameter(name="error")] = None,
    ) -> Redirect:
        expected_state = request.session.pop(_STATE_KEY, None)
        next_path = request.session.pop(_NEXT_KEY, None) or ACCOUNT_PATH
        if not oauth_state or not expected_state or not secrets.compare_digest(oauth_state, expected_state):
            return _back("state")
        if oauth_error or not code:
            return _back("battlenet_denied")
        if optional_member is None:
            return _back("signin_first")
        client_id, client_secret = web_settings.BATTLENET_CLIENT_ID, web_settings.BATTLENET_CLIENT_SECRET
        if client_id is None or client_secret is None:
            return _back("battlenet_not_configured")
        try:
            token = await exchange_code(
                battlenet_client,
                client_id=client_id,
                client_secret=client_secret.get_secret_value(),
                redirect_uri=f"{web_settings.BASE_URL}/auth/battlenet/callback",
                code=code,
            )
            account_id, battletag = await fetch_userinfo(battlenet_client, token)
            await members_service.link_battlenet(optional_member, account_id=account_id, battletag=battletag)
        except BattleNetOAuthError as exc:
            return _back(exc.code)
        return Redirect(next_path)

    @post(
        "/unlink",
        operation_id="BattleNetUnlink",
        status_code=204,
        summary="Unlink my Battle.net account",
        description="Removes the signed-in member's Battle.net account link.",
        response_description="The Battle.net link was removed.",
        security=SECURITY_SESSION,
        responses={401: NOT_SIGNED_IN},
    )
    async def unlink(
        self,
        authenticated_member: NamedDependency[Member],
        members_service: NamedDependency[MembersService],
    ) -> None:
        await members_service.unlink_battlenet(authenticated_member)
