"""MCP token persistence: an officer's own tokens, created/listed/revoked from the officers page.

Mirrors ``EpgpService``'s sync-token methods. The authentication path for the MCP protocol endpoint itself
(hash a bearer token, look up its member, check they're still an officer) lives in ``domain.mcp.auth`` since it
runs outside Litestar's dependency injection (the endpoint is a raw ASGI mount, not a controller).
"""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from litestar.exceptions import NotFoundException
from sqlalchemy import select

from sidequest_common.models import McpToken
from sidequest_common.schemas import McpTokenCreate, McpTokenCreated, McpTokenList, McpTokenSummary

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from sidequest_common.models import Member

_TOKEN_ALPHABET = string.ascii_letters + string.digits + "-_"
_TOKEN_PREFIX = "sqm_"  # noqa: S105 - not a password, a public token format prefix
_TOKEN_RANDOM_LENGTH = 40


def hash_token(token: str) -> str:
    """The sha256 hex digest stored for ``token``; never store the plaintext."""
    return hashlib.sha256(token.encode()).hexdigest()


class McpTokenService:
    """An officer's own MCP tokens: list (non-revoked), create (plaintext shown once), revoke."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_tokens(self, officer: Member) -> McpTokenList:
        """``officer``'s own non-revoked MCP tokens."""
        rows = (
            (
                await self._session.execute(
                    select(McpToken)
                    .where(McpToken.member_id == officer.id, McpToken.revoked_at.is_(None))
                    .order_by(McpToken.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return McpTokenList(
            tokens=[
                McpTokenSummary(id=row.id, name=row.name, created_at=row.created_at, last_used_at=row.last_used_at)
                for row in rows
            ]
        )

    async def create_token(self, officer: Member, data: McpTokenCreate) -> McpTokenCreated:
        """Create an MCP token for ``officer``; the plaintext is returned once and never stored."""
        token = _TOKEN_PREFIX + "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_RANDOM_LENGTH))
        row = McpToken(member_id=officer.id, name=data.name, token_hash=hash_token(token))
        self._session.add(row)
        await self._session.commit()
        return McpTokenCreated(id=row.id, name=row.name, token=token)

    async def revoke_token(self, officer: Member, token_id: UUID) -> None:
        """Revoke one of ``officer``'s own MCP tokens. 404 unknown/not own/already revoked."""
        row = await self._session.get(McpToken, token_id)
        if row is None or row.member_id != officer.id or row.revoked_at is not None:
            msg = f"No MCP token {token_id}"
            raise NotFoundException(msg)
        row.revoked_at = datetime.now(UTC)
        await self._session.commit()
