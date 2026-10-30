"""``/api/me/mcp-tokens``: an officer's own MCP (Model Context Protocol) client tokens.

Gating is dependency-based (``current_officer``, registered app-wide in ``create_app``): declaring the parameter
resolves it, raising 401/403 before the handler body runs.
"""

from uuid import UUID

from litestar import Controller, delete, get, post
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, JSONBody

from sidequest_api.domain.mcp.dependencies import provide_mcp_token_service
from sidequest_api.domain.mcp.services import McpTokenService
from sidequest_common.models import Member
from sidequest_common.schemas import McpTokenCreate, McpTokenCreated, McpTokenList


class McpTokensController(Controller):
    """``/api/me/mcp-tokens``: create/list/revoke the signed-in officer's own MCP tokens."""

    path = "/api/me/mcp-tokens"
    tags = ["MCP"]
    dependencies = {"mcp_token_service": Provide(provide_mcp_token_service)}

    @get("/", operation_id="ListMcpTokens")
    async def list_tokens(
        self, current_officer: NamedDependency[Member], mcp_token_service: NamedDependency[McpTokenService]
    ) -> McpTokenList:
        """The signed-in officer's own non-revoked MCP tokens. 401/403 non-officer."""
        return await mcp_token_service.list_tokens(current_officer)

    @post("/", operation_id="CreateMcpToken", status_code=201)
    async def create_token(
        self,
        data: JSONBody[McpTokenCreate],
        current_officer: NamedDependency[Member],
        mcp_token_service: NamedDependency[McpTokenService],
    ) -> McpTokenCreated:
        """Create an MCP token; the plaintext is returned once and never stored (officer). 401/403 non-officer."""
        return await mcp_token_service.create_token(current_officer, data)

    @delete("/{token_id:uuid}", operation_id="RevokeMcpToken", status_code=204)
    async def revoke_token(
        self,
        token_id: FromPath[UUID],
        current_officer: NamedDependency[Member],
        mcp_token_service: NamedDependency[McpTokenService],
    ) -> None:
        """Revoke one of the signed-in officer's own MCP tokens. 401/403 non-officer, 404 unknown/not own token."""
        await mcp_token_service.revoke_token(current_officer, token_id)
