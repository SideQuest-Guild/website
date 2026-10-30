"""DI providers for the EPGP domain, including the import endpoint's officer-session-or-sync-token guard."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from litestar import Request  # noqa: TC002 - Litestar DI target, needs a real type
from litestar.di import NamedDependency  # noqa: TC002
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.domain.epgp.services import EpgpService
from sidequest_api.lib.member_auth import is_officer
from sidequest_common.models import EpgpSyncToken, Member
from sidequest_common.settings import WebSettings  # noqa: TC001 - Litestar DI target, needs a real type

AUTH_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "
_NO_TOKEN_MESSAGE = "Missing or invalid sync token"  # noqa: S105 - not a password, an error message
_NOT_AN_OFFICER_MESSAGE = "Officers only"


async def provide_epgp_service(db_session: NamedDependency[AsyncSession]) -> EpgpService:
    """An ``EpgpService`` bound to the request's session."""
    return EpgpService(db_session)


async def provide_import_actor(
    request: Request,
    optional_member: NamedDependency[Member | None],
    db_session: NamedDependency[AsyncSession],
    web_settings: NamedDependency[WebSettings],
) -> Member:
    """The import endpoint's guard: an officer session, or a valid ``Bearer`` sync token.

    401 if neither is present/valid, 403 if a valid token's member lost officer access.
    """
    auth_header = request.headers.get(AUTH_HEADER, "")
    if auth_header.startswith(BEARER_PREFIX):
        token = auth_header[len(BEARER_PREFIX) :].strip()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        row = (
            await db_session.execute(select(EpgpSyncToken).where(EpgpSyncToken.token_hash == token_hash))
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            raise NotAuthorizedException(_NO_TOKEN_MESSAGE)
        holder = await db_session.get(Member, row.member_id)
        if holder is None or not is_officer(holder, web_settings.OFFICER_ROLE_IDS):
            raise PermissionDeniedException(_NOT_AN_OFFICER_MESSAGE)
        row.last_used_at = datetime.now(UTC)
        await db_session.commit()
        return holder
    if optional_member is None:
        raise NotAuthorizedException(_NO_TOKEN_MESSAGE)
    if not is_officer(optional_member, web_settings.OFFICER_ROLE_IDS):
        raise PermissionDeniedException(_NOT_AN_OFFICER_MESSAGE)
    return optional_member
