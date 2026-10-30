"""Schemas for an officer's personal MCP (Model Context Protocol) client tokens."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class McpTokenSummary(BaseModel):
    """One non-revoked MCP token, without the secret (``GET /api/me/mcp-tokens``, officer, own tokens only)."""

    id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


class McpTokenList(BaseModel):
    """Response for ``GET /api/me/mcp-tokens`` (officer)."""

    tokens: list[McpTokenSummary]


class McpTokenCreate(BaseModel):
    """Body for ``POST /api/me/mcp-tokens`` (officer)."""

    name: str = Field(min_length=1, max_length=60)


class McpTokenCreated(BaseModel):
    """Response for ``POST /api/me/mcp-tokens``: the token shown once, never stored in plaintext."""

    id: UUID
    name: str
    token: str
