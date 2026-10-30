"""MCP (Model Context Protocol): lets officers drive the guild's Discord and site from a laptop MCP client.

``McpTokensController`` (``/api/me/mcp-tokens``) is a normal Litestar controller for managing an officer's own
tokens. The protocol endpoint itself (``/api/mcp``) is a raw ASGI mount (``build_mcp_asgi_app`` in ``server.py``)
wrapping the official ``mcp`` SDK's streamable-HTTP app, since the SDK's tool functions aren't Litestar handlers.
"""
