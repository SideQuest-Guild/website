"""MCP (Model Context Protocol) officer access tokens."""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class McpToken(UUIDAuditBase):
    """A long-lived bearer token for an officer's personal MCP client (Claude Code, omp), scoped to one member.

    ``token_hash`` is the sha256 hex digest of the token (format ``sqm_`` + 40 url-safe chars); the plaintext is
    shown to the officer once, at creation, and never stored. Every MCP request accepts the token only while its
    member still holds an officer role, checked at request time (not cached on the row), mirroring
    ``EpgpSyncToken``.
    """

    __tablename__ = "mcp_token"
    __table_args__ = {"comment": "Bearer tokens for officers' personal MCP clients (Claude Code, omp)."}

    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("member.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
