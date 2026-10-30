"""Bearer-token authentication for the MCP protocol endpoint.

Mirrors the EPGP sync-token guard (``domain.epgp.dependencies.provide_import_actor``): a sha256-hashed token maps
to a member, who must currently hold an officer role (checked at request time, not cached on the token row).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select

from sidequest_api.lib.member_auth import is_gm, is_officer
from sidequest_common.models import McpToken, Member

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sidequest_common.settings import WebSettings

BEARER_PREFIX = "Bearer "


class McpAuthError(Exception):
    """A missing/invalid/revoked token (401) or a non-officer token holder (403)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


async def authenticate(session: AsyncSession, web_settings: WebSettings, authorization_header: str | None) -> Member:
    """The officer behind ``Authorization: Bearer <token>``. Raises ``McpAuthError`` (401/403) otherwise."""
    if not authorization_header or not authorization_header.startswith(BEARER_PREFIX):
        raise McpAuthError(401, "Missing or invalid MCP token")
    token = authorization_header[len(BEARER_PREFIX) :].strip()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = (await session.execute(select(McpToken).where(McpToken.token_hash == token_hash))).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise McpAuthError(401, "Missing or invalid MCP token")
    member = await session.get(Member, row.member_id)
    if member is None or not is_officer(member, web_settings.OFFICER_ROLE_IDS):
        raise McpAuthError(403, "Officers only")
    row.last_used_at = datetime.now(UTC)
    await session.commit()
    return member


def require_gm(member: Member, web_settings: WebSettings) -> None:
    """Raise ``ToolError`` unless ``member`` is a GM; surfaced to the MCP client as a failed tool call."""
    if not is_gm(member, web_settings.GM_ROLE_IDS):
        msg = "GMs only"
        raise ToolError(msg)
