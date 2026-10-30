"""``/api/me/mcp-tokens``: an officer's own MCP (Model Context Protocol) client tokens.

Gating is dependency-based (``current_officer``, registered app-wide in ``create_app``): declaring the parameter
resolves it, raising 401/403 before the handler body runs.
"""

from typing import Annotated
from uuid import UUID

from litestar import Controller, delete, get, post
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.mcp.dependencies import provide_mcp_token_service
from sidequest_api.domain.mcp.services import McpTokenService
from sidequest_api.lib.openapi import NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import McpTokenCreate, McpTokenCreated, McpTokenList


class McpTokensController(Controller):
    """``/api/me/mcp-tokens``: create/list/revoke the signed-in officer's own MCP tokens."""

    path = "/api/me/mcp-tokens"
    tags = ["MCP tokens"]
    security = SECURITY_SESSION
    dependencies = {"mcp_token_service": Provide(provide_mcp_token_service)}

    @get(
        "/",
        operation_id="ListMcpTokens",
        summary="List my MCP tokens",
        description="Returns the signed-in officer's own non-revoked MCP tokens.",
        response_description="The officer's MCP tokens.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def list_tokens(
        self, current_officer: NamedDependency[Member], mcp_token_service: NamedDependency[McpTokenService]
    ) -> McpTokenList:
        return await mcp_token_service.list_tokens(current_officer)

    @post(
        "/",
        operation_id="CreateMcpToken",
        status_code=201,
        summary="Create an MCP token",
        description=(
            "Creates an MCP token for the signed-in officer. The plaintext token is returned once and never stored."
        ),
        response_description="The new token, including its plaintext value.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def create_token(
        self,
        data: JSONBody[McpTokenCreate],
        current_officer: NamedDependency[Member],
        mcp_token_service: NamedDependency[McpTokenService],
    ) -> McpTokenCreated:
        return await mcp_token_service.create_token(current_officer, data)

    @delete(
        "/{token_id:uuid}",
        operation_id="RevokeMcpToken",
        status_code=204,
        summary="Revoke an MCP token",
        description="Revokes one of the signed-in officer's own MCP tokens.",
        response_description="The token was revoked.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="The token does not exist or belongs to someone else."),
        },
    )
    async def revoke_token(
        self,
        token_id: Annotated[UUID, Parameter(description="The MCP token's ID.")],
        current_officer: NamedDependency[Member],
        mcp_token_service: NamedDependency[McpTokenService],
    ) -> None:
        await mcp_token_service.revoke_token(current_officer, token_id)
