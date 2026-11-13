"""Client-side session config and member/officer dependency guards for the member hub.

Session cookie stores only the member id. ``current_member``/``current_officer`` are registered as app-wide
dependencies (``create_app``); handlers opt in by declaring them as parameters. Unauthenticated/non-member/
non-officer requests raise before the handler body runs, so this plays the role of a guard without needing its
own database session (it reuses the request's ``db_session``).
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from litestar import Request  # noqa: TC002 - these providers are Litestar DI targets, need real types
from litestar.di import NamedDependency  # noqa: TC002
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from litestar.middleware.session.client_side import CookieBackendConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sidequest_common.settings import WebSettings

from sidequest_api.lib.auth import is_valid_api_key
from sidequest_common.models import EpgpSyncToken, Member

logger = logging.getLogger(__name__)

SESSION_COOKIE_KEY = "sq_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
AUTH_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "
_NO_SESSION_MESSAGE = "Not authenticated"
_NOT_A_MEMBER_MESSAGE = "Not a guild member"
_NOT_AN_OFFICER_MESSAGE = "Officers only"
_NOT_A_GM_MESSAGE = "GMs only"


def build_session_config(web_settings: WebSettings) -> CookieBackendConfig:
    """Client-side (encrypted cookie) session config, cookie ``sq_session``, 30-day max age.

    The secret is hashed down to 32 bytes (AES-256) regardless of its length. If ``WEB_SESSION_SECRET`` is unset,
    a random per-process secret is generated and a warning is logged (sessions won't survive a restart).
    """
    if web_settings.SESSION_SECRET is not None:
        raw_secret = web_settings.SESSION_SECRET.get_secret_value()
    else:
        logger.warning(
            "WEB_SESSION_SECRET is not set; using a random per-process secret. Sessions will not survive a restart."
        )
        raw_secret = secrets.token_urlsafe(32)
    return CookieBackendConfig(
        secret=hashlib.sha256(raw_secret.encode()).digest(),
        key=SESSION_COOKIE_KEY,
        max_age=SESSION_MAX_AGE,
        secure=web_settings.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


async def provide_authenticated_member(request: Request, db_session: NamedDependency[AsyncSession]) -> Member:
    """The signed-in member, regardless of guild membership. 401 if not logged in.

    Used by ``GET /api/me``, which must return a profile (with ``is_guild_member: false``) for signed-in
    non-members so the account page can show them the invite, rather than 403ing them away from their own data.
    """
    member_id = request.session.get("member_id")
    member = await db_session.get(Member, int(member_id)) if member_id is not None else None
    if member is None:
        raise NotAuthorizedException(_NO_SESSION_MESSAGE)
    return member


async def provide_current_member(authenticated_member: NamedDependency[Member]) -> Member:
    """The "member" guard: signed in AND a guild member. 401 not logged in / 403 not a member."""
    if not authenticated_member.is_guild_member:
        raise PermissionDeniedException(_NOT_A_MEMBER_MESSAGE)
    return authenticated_member


async def provide_optional_member(request: Request, db_session: NamedDependency[AsyncSession]) -> Member | None:
    """The signed-in member if there is one, else ``None``. Never raises; for public endpoints that personalize."""
    member_id = request.session.get("member_id")
    if member_id is None:
        return None
    return await db_session.get(Member, int(member_id))


async def _resolve_sync_token_holder(request: Request, db_session: AsyncSession) -> Member | None:
    """The sync token's holder, for a request carrying a ``Bearer`` sync token; ``None`` if there is no such header.

    401s if the header is present but the token is unknown or revoked. Does not check guild membership; callers
    decide. Shares the sync-token lookup used by ``domain/epgp/dependencies.py``'s import/game-import guards.
    """
    auth_header = request.headers.get(AUTH_HEADER, "")
    if not auth_header.startswith(BEARER_PREFIX):
        return None
    token = auth_header[len(BEARER_PREFIX) :].strip()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = (
        await db_session.execute(select(EpgpSyncToken).where(EpgpSyncToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise NotAuthorizedException(_NO_SESSION_MESSAGE)
    holder = await db_session.get(Member, row.member_id)
    if holder is None:
        raise NotAuthorizedException(_NO_SESSION_MESSAGE)
    row.last_used_at = datetime.now(UTC)
    await db_session.commit()
    return holder


async def provide_member_or_sync_token(request: Request, db_session: NamedDependency[AsyncSession]) -> Member:
    """The "member or sync token" guard: a guild member's session, or a valid ``Bearer`` sync token.

    401 if neither is present, 403 if the session's member (or the token's holder) is not a guild member. Used
    in place of ``current_member`` by routes SideQuest Companion also reads with its sync token.
    """
    holder = await _resolve_sync_token_holder(request, db_session)
    if holder is not None:
        if not holder.is_guild_member:
            raise PermissionDeniedException(_NOT_A_MEMBER_MESSAGE)
        return holder
    member_id = request.session.get("member_id")
    member = await db_session.get(Member, int(member_id)) if member_id is not None else None
    if member is None:
        raise NotAuthorizedException(_NO_SESSION_MESSAGE)
    if not member.is_guild_member:
        raise PermissionDeniedException(_NOT_A_MEMBER_MESSAGE)
    return member


async def provide_optional_member_or_sync_token(
    request: Request, db_session: NamedDependency[AsyncSession]
) -> Member | None:
    """The signed-in member or sync token holder if there is one, else ``None``.

    For public GET routes that personalize for both a session and SideQuest Companion's sync token. 403s if a
    valid token's holder is no longer a guild member (same rule as ``provide_member_or_sync_token``); an
    anonymous/plain-session visitor is left to the route's own membership check, same as ``optional_member``.
    """
    holder = await _resolve_sync_token_holder(request, db_session)
    if holder is not None:
        if not holder.is_guild_member:
            raise PermissionDeniedException(_NOT_A_MEMBER_MESSAGE)
        return holder
    member_id = request.session.get("member_id")
    if member_id is None:
        return None
    return await db_session.get(Member, int(member_id))


def create_full_access_provider(api_key: str) -> Callable[[Request, Member | None], Awaitable[bool]]:
    """Dependency factory: whether the caller may see full event data (signed in, or the bot's ``X-API-Key``).

    Used by public endpoints that personalize but also redact personal data (signups, Discord interest names)
    from anonymous site visitors while still serving the bot, which authenticates with ``X-API-Key`` instead
    of a session.
    """

    async def provide_full_access(request: Request, optional_member: NamedDependency[Member | None]) -> bool:
        if optional_member is not None:
            return True
        return is_valid_api_key(request, api_key)

    return provide_full_access


def create_member_or_bot_provider(api_key: str) -> Callable[[Request, Member | None], Awaitable[None]]:
    """Dependency factory: 401 unless the caller is signed in or presents the bot's ``X-API-Key``.

    Unlike :func:`create_full_access_provider` (a boolean an endpoint uses to redact data for anonymous visitors),
    this guard rejects the request outright: for endpoints with no anonymous-visitor view at all (Hall of Heroes).
    """

    async def provide_member_or_bot(request: Request, optional_member: NamedDependency[Member | None]) -> None:
        if optional_member is None and not is_valid_api_key(request, api_key):
            raise NotAuthorizedException(_NO_SESSION_MESSAGE)

    return provide_member_or_bot


def is_officer(member: Member, officer_role_ids: list[int]) -> bool:
    """Whether ``member`` holds any of ``officer_role_ids`` (their Discord roles as of their last sign-in)."""
    return bool(set(officer_role_ids) & set(member.roles))


def create_current_officer_provider(officer_role_ids: list[int]) -> Callable[[Member], Awaitable[Member]]:
    """Dependency factory: the signed-in member, 403 unless they hold one of ``officer_role_ids``."""

    async def provide_current_officer(current_member: NamedDependency[Member]) -> Member:
        if not is_officer(current_member, officer_role_ids):
            raise PermissionDeniedException(_NOT_AN_OFFICER_MESSAGE)
        return current_member

    return provide_current_officer


def is_gm(member: Member, gm_role_ids: list[int]) -> bool:
    """Whether ``member`` holds any of ``gm_role_ids`` (their Discord roles as of their last sign-in)."""
    return bool(set(gm_role_ids) & set(member.roles))


def create_current_gm_provider(gm_role_ids: list[int]) -> Callable[[Member], Awaitable[Member]]:
    """Dependency factory: the signed-in member, 403 unless they hold one of ``gm_role_ids``."""

    async def provide_current_gm(current_member: NamedDependency[Member]) -> Member:
        if not is_gm(current_member, gm_role_ids):
            raise PermissionDeniedException(_NOT_A_GM_MESSAGE)
        return current_member

    return provide_current_gm


def safe_next_path(value: str | None) -> str | None:
    r"""Sanitize a ``?next=`` redirect target: only a same-site path starting with a single ``/`` is accepted.

    Backslashes, whitespace and control characters are rejected anywhere: browsers drop tab/CR/LF from URLs and
    treat ``\`` as ``/``, so ``/<TAB>/evil.example`` or ``/\evil.example`` would otherwise become ``//evil.example``.
    """
    if not value or not value.startswith("/") or value.startswith("//") or "://" in value:
        return None
    if any(char == "\\" or char.isspace() or not char.isprintable() for char in value):
        return None
    return value
