"""Client-side session config and member/officer dependency guards for the member hub.

Session cookie stores only the member id. ``current_member``/``current_officer`` are registered as app-wide
dependencies (``create_app``); handlers opt in by declaring them as parameters. Unauthenticated/non-member/
non-officer requests raise before the handler body runs, so this plays the role of a guard without needing its
own database session (it reuses the request's ``db_session``).
"""

import hashlib
import logging
import secrets
from typing import TYPE_CHECKING

from litestar import Request  # noqa: TC002 - these providers are Litestar DI targets, need real types
from litestar.di import NamedDependency  # noqa: TC002
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from litestar.middleware.session.client_side import CookieBackendConfig
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sidequest_common.settings import WebSettings

from sidequest_common.models import Member

logger = logging.getLogger(__name__)

SESSION_COOKIE_KEY = "sq_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
_NO_SESSION_MESSAGE = "Not authenticated"
_NOT_A_MEMBER_MESSAGE = "Not a guild member"
_NOT_AN_OFFICER_MESSAGE = "Officers only"


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


def create_current_officer_provider(officer_role_ids: list[int]) -> Callable[[Member], Awaitable[Member]]:
    """Dependency factory: the signed-in member, 403 unless they hold one of ``officer_role_ids``."""
    officer_roles = set(officer_role_ids)

    async def provide_current_officer(current_member: NamedDependency[Member]) -> Member:
        if not officer_roles & set(current_member.roles):
            raise PermissionDeniedException(_NOT_AN_OFFICER_MESSAGE)
        return current_member

    return provide_current_officer


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
