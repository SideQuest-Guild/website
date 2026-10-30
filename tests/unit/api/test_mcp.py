"""Tests for the MCP (Model Context Protocol) endpoint: auth, the role guard, audits, and a real MCP client."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import httpx2
import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import select

from sidequest_api.app import create_app
from sidequest_api.domain.members.services import MembersService
from sidequest_common.models import McpToken, Member, OfficerAudit
from sidequest_common.settings import APISettings, DatabaseSettings, WebSettings
from tests.conftest import GUILD_ID, TEST_API_KEY

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

OFFICER_ROLE_ID = 999_111
GM_ROLE_ID = 999_222
DANGEROUS_ROLE_ID = 999_333

MESSAGE_ENDPOINT_HEADERS = {"Accept": "application/json, text/event-stream"}


def _bot_discord_transport() -> httpx.MockTransport:
    """Fakes the Discord bot REST calls MCP tools make: roles, channels, members, messages, audit log."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/roles"):
            return httpx.Response(
                200,
                json=[
                    {"id": str(GUILD_ID), "name": "@everyone", "position": 0, "managed": False, "permissions": "0"},
                    {"id": "555", "name": "Raider", "position": 1, "managed": False, "permissions": "0"},
                    {
                        "id": str(DANGEROUS_ROLE_ID),
                        "name": "Admin",
                        "position": 2,
                        "managed": False,
                        "permissions": "8",  # administrator bit
                    },
                    {"id": "999", "name": "Bot", "position": 3, "managed": True, "permissions": "0"},
                ],
            )
        if path.endswith("/members/@me"):
            return httpx.Response(200, json={"roles": ["999"]})
        if path.endswith("/channels"):
            return httpx.Response(200, json=[{"id": "777", "name": "general", "type": 0, "parent_id": None}])
        if path.endswith("/messages") and request.method == "GET":
            return httpx.Response(200, json=[])
        if path.endswith("/messages") and request.method == "POST":
            return httpx.Response(200, json={"id": "900100", "channel_id": "777"})
        if "/messages/" in path and request.method == "PATCH":
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[-1], "channel_id": "777"})
        if path.endswith("/roles/555") or f"/roles/{DANGEROUS_ROLE_ID}" in path:
            return httpx.Response(204)
        if path.endswith("/audit-logs"):
            return httpx.Response(200, json={"audit_log_entries": []})
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.MockTransport(handler)


@pytest.fixture
def mcp_web_settings() -> WebSettings:
    return WebSettings(
        GUILD_ID=GUILD_ID, OFFICER_ROLE_IDS=[OFFICER_ROLE_ID], GM_ROLE_IDS=[GM_ROLE_ID], COOKIE_SECURE=False
    )


@pytest.fixture
def mcp_app(database_url: str, mcp_web_settings: WebSettings, monkeypatch: pytest.MonkeyPatch) -> Litestar:
    """App with the bot token configured, behind a mocked Discord transport."""
    monkeypatch.setenv("DISCORD_TOKEN", "fake-bot-token")
    return create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        mcp_web_settings,
        discord_transport=_bot_discord_transport(),
    )


@pytest.fixture
async def mcp_client(mcp_app: Litestar) -> AsyncIterator[AsyncTestClient[Litestar]]:
    async with AsyncTestClient(app=mcp_app) as client:
        yield client


async def _seed_member(
    db_sessionmaker: async_sessionmaker[AsyncSession], *, roles: list[int], discord_id: int = 1001
) -> tuple[int, str]:
    """Insert a signed-in member and an MCP token for them; returns ``(member_id, plaintext_token)``."""
    token = "sqm_" + "x" * 40
    async with db_sessionmaker() as session:
        member = Member(discord_id=discord_id, username="officer", roles=roles, is_guild_member=True)
        session.add(member)
        await session.flush()
        session.add(McpToken(member_id=member.id, name="test token", token_hash=_hash(token)))
        await session.commit()
        member_id = member.id
    return member_id, token


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _call_tool(
    client: AsyncTestClient[Litestar], token: str | None, name: str, arguments: dict | None = None
) -> httpx.Response:
    headers = dict(MESSAGE_ENDPOINT_HEADERS)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return await client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
        headers=headers,
    )


# --- Auth ------------------------------------------------------------------------------------------------------


async def test_missing_token_is_401(mcp_client: AsyncTestClient) -> None:
    response = await _call_tool(mcp_client, None, "whoami")
    assert response.status_code == 401


async def test_bad_token_is_401(mcp_client: AsyncTestClient) -> None:
    response = await _call_tool(mcp_client, "sqm_not-a-real-token", "whoami")
    assert response.status_code == 401


async def test_revoked_token_is_401(
    mcp_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID])
    async with db_sessionmaker() as session:
        row = (await session.execute(select(McpToken).where(McpToken.member_id == member_id))).scalar_one()
        row.revoked_at = datetime.now(UTC)
        await session.commit()
    response = await _call_tool(mcp_client, token, "whoami")
    assert response.status_code == 401


async def test_non_officer_token_is_403(
    mcp_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    _member_id, token = await _seed_member(db_sessionmaker, roles=[])
    response = await _call_tool(mcp_client, token, "whoami")
    assert response.status_code == 403


async def test_officer_token_can_call_whoami(
    mcp_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    _member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID])
    response = await _call_tool(mcp_client, token, "whoami")
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["isError"] is False
    assert body["result"]["structuredContent"]["is_gm"] is False


async def test_find_member_reports_renown_and_attendance(
    mcp_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    _member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID])
    response = await _call_tool(mcp_client, token, "find_member", {"query": "officer"})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    [match] = result["structuredContent"]["result"]
    assert match["username"] == "officer"
    assert match["renown"] == 0
    assert match["raids_attended"] == 0
    assert match["attendance_rate"] == 0.0


# --- GM gating ---------------------------------------------------------------------------------------------------


async def test_gm_only_tool_is_refused_for_plain_officer(
    mcp_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    _member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID])
    response = await _call_tool(mcp_client, token, "attendance_report", {})
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["isError"] is True


async def test_gm_only_tool_works_for_gm(
    mcp_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    _member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID, GM_ROLE_ID])
    response = await _call_tool(mcp_client, token, "attendance_report", {})
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["isError"] is False


# --- Role guard ----------------------------------------------------------------------------------------------------


async def test_role_guard_refuses_a_dangerous_role(
    mcp_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    _member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID])
    response = await _call_tool(
        mcp_client, token, "add_member_role", {"member_discord_id": "2002", "role_id": str(DANGEROUS_ROLE_ID)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["isError"] is True
    assert "permission" in body["result"]["content"][0]["text"].lower()


async def test_role_guard_allows_a_safe_role(
    mcp_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    _member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID])
    response = await _call_tool(mcp_client, token, "add_member_role", {"member_discord_id": "2002", "role_id": "555"})
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["isError"] is False


# --- Audit log -------------------------------------------------------------------------------------------------


async def test_mutating_tool_writes_an_audit_row(
    mcp_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID])
    response = await _call_tool(mcp_client, token, "post_message", {"channel_id": "777", "content": "hello"})
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False
    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(OfficerAudit).where(OfficerAudit.actor_member_id == member_id)))
            .scalars()
            .all()
        )
    assert any(row.action == "mcp.post_message" for row in rows)


async def test_create_event_writes_an_audit_row_and_returns_the_event(
    mcp_client: AsyncTestClient, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID])
    response = await _call_tool(
        mcp_client,
        token,
        "create_event",
        {"kind": "social", "title": "MCP Test Night", "starts_at": "2026-12-01T20:00:00+00:00"},
    )
    assert response.status_code == 200
    body = response.json()["result"]
    assert body["isError"] is False
    assert body["structuredContent"]["title"] == "MCP Test Night"
    async with db_sessionmaker() as session:
        rows = (
            (await session.execute(select(OfficerAudit).where(OfficerAudit.actor_member_id == member_id)))
            .scalars()
            .all()
        )
    assert any(row.action == "mcp.create_event" for row in rows)


# --- delete_account cleanup -------------------------------------------------------------------------------------


async def test_delete_account_removes_mcp_tokens(db_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    member_id, _token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID])
    async with db_sessionmaker() as session:
        member = await session.get(Member, member_id)
        assert member is not None
        await MembersService(session).delete_account(member)
        remaining = (await session.execute(select(McpToken).where(McpToken.member_id == member_id))).scalars().all()
        assert remaining == []


# --- Real MCP client over streamable HTTP -------------------------------------------------------------------------


@pytest.mark.enable_socket
async def test_real_mcp_client_lists_tools_and_calls_a_read_tool_and_create_event(
    database_url: str,
    mcp_web_settings: WebSettings,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drives the endpoint with the official ``mcp`` SDK client over real streamable HTTP (a live uvicorn server)."""
    import uvicorn
    from mcp.client import Client
    from mcp.client.streamable_http import streamable_http_client

    monkeypatch.setenv("DISCORD_TOKEN", "fake-bot-token")
    _member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID], discord_id=5005)
    app = create_app(
        DatabaseSettings(URL=database_url),
        APISettings(KEY=TEST_API_KEY),
        mcp_web_settings,
        discord_transport=_bot_discord_transport(),
    )
    port = 18732
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    try:
        for _ in range(50):
            if server.started:
                break
            await asyncio.sleep(0.1)
        http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
        async with Client(
            streamable_http_client(f"http://127.0.0.1:{port}/api/mcp", http_client=http_client), raise_exceptions=True
        ) as client:
            tools = await client.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert "whoami" in tool_names
            assert "create_event" in tool_names

            whoami_result = await client.call_tool("whoami", {})
            assert whoami_result.is_error is False

            create_result = await client.call_tool(
                "create_event",
                {"kind": "social", "title": "Real Client Night", "starts_at": "2026-12-05T20:00:00+00:00"},
            )
            assert create_result.is_error is False
            assert create_result.structured_content["title"] == "Real Client Night"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# --- Discord not configured -------------------------------------------------------------------------------------


async def test_discord_tool_fails_clearly_when_bot_token_unset(
    database_url: str,
    mcp_web_settings: WebSettings,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    _member_id, token = await _seed_member(db_sessionmaker, roles=[OFFICER_ROLE_ID], discord_id=6006)
    app = create_app(DatabaseSettings(URL=database_url), APISettings(KEY=TEST_API_KEY), mcp_web_settings)
    async with AsyncTestClient(app=app) as client:
        response = await _call_tool(client, token, "list_channels")
    assert response.status_code == 200
    body = response.json()["result"]
    assert body["isError"] is True
    assert "isn't configured" in body["content"][0]["text"].lower()
