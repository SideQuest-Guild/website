"""OpenAPI document shaping shared by every controller: tags, tag groups, and security schemes.

The document groups its ~50 tags by who calls them (``TAG_GROUPS``), so the Scalar reference
(``/api-reference/``) shows a sectioned sidebar instead of one flat alphabetical list. OpenAPI itself has no
grouping field; Scalar reads the de-facto ``x-tagGroups`` extension instead. Litestar's OpenAPI dataclasses
(``litestar.openapi.spec``) have no generic "extensions" dict to carry an ``x-`` key through to the served
JSON, so ``OpenAPIExtensionsMiddleware`` adds it to the already-rendered JSON response for ``/schema/openapi.json``
and ``/schema/openapi.yaml`` instead. This is the officially documented extension point for the OpenAPI routes:
``OpenAPIConfig.openapi_router`` exists precisely "to customize the configuration of the router used to serve the
documentation endpoints [...] you can add middleware or guards to the router."
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated, Any

from litestar.enums import ScopeType
from litestar.openapi.datastructures import ResponseSpec
from litestar.openapi.spec import Reference, SecurityScheme, Tag
from litestar.params import PathParameter
from litestar.serialization import decode_json, encode_json

if TYPE_CHECKING:
    from litestar.types import ASGIApp, HTTPResponseBodyEvent, HTTPResponseStartEvent, Message, Receive, Scope, Send

# ---------------------------------------------------------------------------------------------------------------
# Security schemes. Every route's ``security`` list (set on the guild API router, on member/officer/GM-gated
# controllers, or per operation for mixed controllers) names one of these.
# ---------------------------------------------------------------------------------------------------------------

SECURITY_SCHEME_SESSION = "SessionAuth"
SECURITY_SCHEME_API_KEY = "ApiKeyAuth"
SECURITY_SCHEME_SYNC_TOKEN = "SyncTokenAuth"  # noqa: S105 - an OpenAPI security scheme name, not a secret
SECURITY_SCHEME_MCP_TOKEN = "McpTokenAuth"  # noqa: S105 - an OpenAPI security scheme name, not a secret

SESSION_COOKIE_NAME = "sq_session"

SECURITY_SCHEMES: dict[str, Reference | SecurityScheme] = {
    SECURITY_SCHEME_SESSION: SecurityScheme(
        type="apiKey",
        security_scheme_in="cookie",
        name=SESSION_COOKIE_NAME,
        description="The cookie set after a member signs in with Discord at `/auth/discord/login`.",
    ),
    SECURITY_SCHEME_API_KEY: SecurityScheme(
        type="apiKey",
        security_scheme_in="header",
        name="X-API-Key",
        description="The Discord bot's shared key. Only the bot sends this header.",
    ),
    SECURITY_SCHEME_SYNC_TOKEN: SecurityScheme(
        type="http",
        scheme="bearer",
        bearer_format="sync token",
        description="A sync token from `/api/epgp/sync-tokens`, sent by the addon's upload tool.",
    ),
    SECURITY_SCHEME_MCP_TOKEN: SecurityScheme(
        type="http",
        scheme="bearer",
        bearer_format="MCP token",
        description="An MCP token from `/api/me/mcp-tokens`, sent by an MCP client.",
    ),
}

SECURITY_SESSION: list[dict[str, list[str]]] = [{SECURITY_SCHEME_SESSION: []}]
SECURITY_API_KEY: list[dict[str, list[str]]] = [{SECURITY_SCHEME_API_KEY: []}]
# The import endpoint accepts either an officer's session or a sync token.
SECURITY_SESSION_OR_SYNC_TOKEN: list[dict[str, list[str]]] = [
    {SECURITY_SCHEME_SESSION: []},
    {SECURITY_SCHEME_SYNC_TOKEN: []},
]
# SideQuest Companion's own routes take only its Bearer sync token.
SECURITY_SYNC_TOKEN: list[dict[str, list[str]]] = [{SECURITY_SCHEME_SYNC_TOKEN: []}]

# ---------------------------------------------------------------------------------------------------------------
# Shared response descriptions. Compose into a handler's ``responses={...}`` mapping, e.g.
# ``responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER, 404: ResponseSpec(None, description="Unknown addon ID.")}``.
# ---------------------------------------------------------------------------------------------------------------

NOT_SIGNED_IN = ResponseSpec(None, description="You are not signed in.")
NOT_A_MEMBER = ResponseSpec(None, description="You signed in, but are not a guild member.")
NOT_AN_OFFICER = ResponseSpec(None, description="You are not an officer.")
NOT_A_GM = ResponseSpec(None, description="You are not a Quest Master or Quest Guide.")
BAD_API_KEY = ResponseSpec(None, description="The `X-API-Key` header is missing or wrong.")
BAD_SYNC_OR_SESSION = ResponseSpec(
    None, description="You are not signed in as an officer, and the sync token is missing, wrong, or revoked."
)

# ---------------------------------------------------------------------------------------------------------------
# Tags and tag groups. ``TAGS`` becomes ``OpenAPIConfig.tags`` (so every tag gets its description); ``TAG_GROUPS``
# becomes the ``x-tagGroups`` extension. Every tag here MUST be in exactly one group, and every tag a controller
# or route handler sets MUST be listed here (``test_openapi_docs.py`` checks both).
# ---------------------------------------------------------------------------------------------------------------

TAG_GROUPS: dict[str, dict[str, str]] = {
    "Public": {
        "Events": "Upcoming and past guild events. Anyone may read them.",
        "Event series": "Repeating event templates, like a weekly raid night. Anyone may read them.",
        "Addons": "The addons the guild recommends. Anyone may read the list.",
        "Recruiting": "The guild's current recruiting needs. Anyone may read them.",
        "Loot ledger": "SQL (SideQuest Loot) standings, history, and boss progress. Anyone may read them.",
        "Guild news": "Guild news and posted announcements. Anyone may read them.",
        "Discord status": "The guild's live Discord voice and member counts. Anyone may read them.",
        "Calendar feed": "A member's private calendar feed. Anyone with the feed link can read it; no sign-in needed.",
    },
    "Members": {
        "My account": "The signed-in member's own profile. A member must be signed in.",
        "Event signups": "A signed-in member's own event signup. A member must be signed in.",
        "My away dates": "A signed-in member's own away dates. A member must be signed in.",
        "My calendar": "A signed-in member's own private calendar link. A member must be signed in.",
        "My characters": "A signed-in member's own claimed characters. A member must be signed in.",
        "Discord presence": "Who is online in the guild's Discord right now. A member must be signed in.",
        "Hall of Heroes": "The guild's season leaderboard and member profiles. A member must be signed in.",
        "Guild hub": "Roster, crafters, and bank browsing for signed-in members. A member must be signed in.",
        "SideQuest Companion": (
            "Sign the desktop companion in from the browser, and manage your own sync tokens. A member must be signed "
            "in, or the companion sends its sync token."
        ),
    },
    "Sign-in and accounts": {
        "Discord sign-in": "Sign in with Discord and sign out. No sign-in needed to start.",
        "Battle.net account": "Link or unlink a Battle.net account. A member must be signed in.",
    },
    "Officers": {
        "Event scheduling": "Create, edit, and chart guild events. An officer must be signed in.",
        "Event series management": "Create, edit, and end repeating event series. An officer must be signed in.",
        "Addon catalog": "Add, edit, and remove addons from the list. An officer must be signed in.",
        "Recruiting needs": "Set the guild's recruiting needs. An officer must be signed in.",
        "Guild hub admin": "Post guild announcements. An officer must be signed in.",
        "EPGP recruits": "Review recruiting candidates and cast votes. An officer must be signed in.",
        "Member notes": "Officer notes about members and characters. An officer must be signed in.",
        "Loot administration": "Manage SQL standings, characters, and roster entries. An officer must be signed in.",
        "Sync tokens": "Create sync tokens for the addon uploader. An officer must be signed in.",
        "Attendance": "Review events and mark who attended. An officer must be signed in.",
    },
    "Game Masters": {
        "GM console": "Member lookup, audit log, and case review for Game Masters. A Game Master must be signed in.",
        "Attendance reports": "Attendance reports and trend charts. A Game Master must be signed in.",
        "Roster confirmation": "Confirm or clear a member's in-game roster status. A Game Master must be signed in.",
    },
    "Addon sync": {
        "EPGP import": "Upload an SQX1 export from the addon. An officer session or a valid sync token works.",
    },
    "MCP": {
        "MCP tokens": "Create and revoke bearer tokens for MCP clients. An officer must be signed in.",
    },
    "System": {
        "System": "Process and database health checks, for monitoring.",
    },
    "Discord bot": {
        "Guild settings": "The guild's configuration. Called by the bot with its shared key.",
        "Leveling": "XP, rank, leaderboard, and level roles. Called by the bot with its shared key.",
        "Moderation cases": "Moderation case records. Called by the bot with its shared key.",
        "Role menus": "Self-assign role menus and their options. Called by the bot with its shared key.",
        "Event sync": "Keeps Discord scheduled events and the site's events in step. Called by the bot.",
        "Discord live": "Reports the guild's live voice and member counts. Called by the bot with its shared key.",
        "Member links": "Who has signed in and linked Battle.net. Called by the bot with its shared key.",
        "Member profiles": "Syncs linked members' current Discord profiles. Called by the bot with its shared key.",
        "Guild roles": "The guild's full current Discord role set. Called by the bot with its shared key.",
        "Role resets": "Discord roles owed after a site account deletion. Called by the bot with its shared key.",
        "Signup notices": "Reminders sent to members who have not signed up. Called by the bot with its shared key.",
        "Weekly board": "The week's scheduled events, for the Discord weekly-board post. Called by the bot.",
        "Discord signups": "A member's event signup, looked up by Discord ID. Called by the bot with its shared key.",
        "Away status": "Which members are away today. Called by the bot with its shared key.",
        "Attendance voice": "Voice-channel minutes per running event. Called by the bot with its shared key.",
        "Badges": "Badge role state and pending announcements. Called by the bot with its shared key.",
        "Guild announcements": "The bot's queue of guild announcements still to post. Called by the bot.",
    },
}

TAGS: list[Tag] = [
    Tag(name=tag_name, description=description)
    for group in TAG_GROUPS.values()
    for tag_name, description in group.items()
]

X_TAG_GROUPS: list[dict[str, Any]] = [
    {"name": group_name, "tags": list(group.keys())} for group_name, group in TAG_GROUPS.items()
]

# ---------------------------------------------------------------------------------------------------------------
# A shared path-parameter description: nearly every bot route under ``/api/guilds/{guild_id}`` takes this.
# ---------------------------------------------------------------------------------------------------------------

GuildIdPath = Annotated[int, PathParameter(description="The Discord server ID. Only the SideQuest server works.")]

# ---------------------------------------------------------------------------------------------------------------
# Litestar adds a 400 response to every operation with a typed/constrained path or query parameter on its own
# (the built-in validation-failure response), using the stock ``HTTPStatus(400).description`` text. Setting
# ``responses={400: ResponseSpec(...)}`` on a handler does override it, but that would mean repeating the same
# sentence on nearly every operation in the document (almost all of them take a typed parameter somewhere), so
# it is rewritten once here instead, for every status code, wherever a handler left the auto-generated text in
# place.
# ---------------------------------------------------------------------------------------------------------------

_STOCK_RESPONSE_REWRITES: dict[int, str] = {
    400: "The request has a value that is not valid. The response says which one.",
}


def _rewrite_stock_responses(document: dict[str, Any]) -> None:
    for path_item in document.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for status_code, response in operation.get("responses", {}).items():
                try:
                    status = int(status_code)
                except ValueError:
                    continue
                stock_text = HTTPStatus(status).description if status in _STOCK_RESPONSE_REWRITES else None
                if stock_text is not None and response.get("description") == stock_text:
                    response["description"] = _STOCK_RESPONSE_REWRITES[status]


def _fill_missing_schema_descriptions(document: dict[str, Any]) -> None:
    """Backfill a component schema's ``description`` from its Python class's docstring.

    Litestar's ``PydanticSchemaPlugin`` sets a component schema's ``title`` from the model but never its
    ``description`` (unlike plain ``pydantic`` model_json_schema(), which does), so every schema otherwise needs
    its own ``json_schema_extra``/``ConfigDict(title=...)`` workaround to get one. Pulling it from the model's
    docstring here, once, lets every schema file in ``sidequest_common.schemas`` just write a normal docstring.
    """
    import sidequest_common.schemas as schemas_module  # noqa: PLC0415 - optional, only used while rewriting docs

    schemas = document.get("components", {}).get("schemas", {})
    for name, schema in schemas.items():
        if schema.get("description", "").strip():
            continue
        model = getattr(schemas_module, name, None)
        doc = getattr(model, "__doc__", None)
        if doc and doc.strip():
            schema["description"] = " ".join(line.strip() for line in doc.strip().splitlines() if line.strip())


class OpenAPIExtensionsMiddleware:
    """Adds the ``x-tagGroups`` extension to the served OpenAPI JSON/YAML.

    Also rewrites Litestar's auto-generated stock response text; everything else passes through. Attached to
    ``OpenAPIConfig.openapi_router`` (not the whole app), so it only ever sees the handful of ``/schema/*``
    requests. Litestar's OpenAPI document (``litestar.openapi.spec.OpenAPI``) has no field for arbitrary ``x-``
    extensions, so this rewrites the already-rendered response body instead of the document.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass every request through unchanged except ``GET .../openapi.json``, whose body is rewritten."""
        if scope["type"] != ScopeType.HTTP or not scope["path"].endswith("/openapi.json"):
            await self.app(scope, receive, send)
            return

        start_message: HTTPResponseStartEvent | None = None
        body_parts: list[bytes] = []

        async def rewriting_send(message: Message) -> None:
            nonlocal start_message
            if message["type"] == "http.response.start":
                start_message = message
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            body_parts.append(message.get("body", b""))
            if message.get("more_body"):
                return
            document = decode_json(b"".join(body_parts))
            document["x-tagGroups"] = X_TAG_GROUPS
            _rewrite_stock_responses(document)
            _fill_missing_schema_descriptions(document)
            body = encode_json(document)
            assert start_message is not None  # noqa: S101 - "http.response.start" always precedes the body
            headers = [
                (name, value) for name, value in start_message.get("headers", []) if name.lower() != b"content-length"
            ]
            headers.append((b"content-length", str(len(body)).encode("latin-1")))
            start: HTTPResponseStartEvent = {
                "type": "http.response.start",
                "status": start_message["status"],
                "headers": headers,
            }
            end: HTTPResponseBodyEvent = {"type": "http.response.body", "body": body, "more_body": False}
            await send(start)
            await send(end)

        await self.app(scope, receive, rewriting_send)
