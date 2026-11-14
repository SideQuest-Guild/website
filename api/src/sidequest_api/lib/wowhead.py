"""Wowhead: item display ids for the 3D character model, and the model viewer's files.

The character page draws a character with Wowhead's model viewer (``wow.zamimg.com``). Wowhead answers the viewer's
file requests only from its own pages (any other ``Origin`` gets 403), so the site relays them: the browser asks
``/api/modelviewer/...`` and this module fetches the same path from Wowhead's WoW: Forever ("classicplus") files.
Battle.net names a character's worn items but not how they look, so each item's display id and inventory type come
from Wowhead's item XML, cached for the life of the process (an item's look only changes with a game patch).

One HTTP client serves the whole app, opened by ``wowhead_lifespan``; tests pass a mock transport to ``create_app``.
"""

import asyncio
import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, NamedTuple

import httpx
from litestar.datastructures import State  # noqa: TC002 - provide_wowhead is a Litestar DI target

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from contextlib import AbstractAsyncContextManager

    from litestar import Litestar

WOWHEAD_STATE_KEY = "wowhead"
ITEM_XML_URL = "https://www.wowhead.com/forever/item={item_id}&xml"
MODEL_FILES_URL = "https://wow.zamimg.com/modelviewer/classicplus/"
USER_AGENT = "SideQuest guild site (+https://sidequest-guild.com)"

MODEL_FILE_PATH = re.compile(r"^[a-z0-9]+(?:/[a-z0-9_]+)*/[a-z0-9_]+\.(?:json|m2|skin|webp|png|bone|anim|skel|phys)$")
"""The viewer's files: ``meta/armor/5/8071.json``, ``m2/959310.m2``, ``textures/959287.webp`` and the like. Lowercase
names in fixed folders, no dots or ``..`` in a folder, one known extension: never a path out of the viewer's files."""

_DISPLAY_ID = re.compile(r'<icon displayId="(\d+)"')
_INVENTORY_TYPE = re.compile(r'<inventorySlot id="(\d+)"')
_LOOKUP_CONCURRENCY = 4


class ItemLook(NamedTuple):
    """How an item looks in the model viewer: its display id and inventory type (Wowhead's ``inventorySlot``)."""

    display_id: int
    inventory_type: int


_item_looks: dict[int, ItemLook | None] = {}
_lookup_semaphore = asyncio.Semaphore(_LOOKUP_CONCURRENCY)


def wowhead_lifespan(
    transport: httpx.AsyncBaseTransport | None = None,
) -> Callable[[Litestar], AbstractAsyncContextManager[None]]:
    """Open the app's Wowhead client when the app starts and close it when the app stops."""

    @asynccontextmanager
    async def lifespan(app: Litestar) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            transport=transport, timeout=20.0, headers={"User-Agent": USER_AGENT}, follow_redirects=False
        ) as client:
            app.state[WOWHEAD_STATE_KEY] = client
            yield

    return lifespan


async def provide_wowhead(state: State) -> httpx.AsyncClient:
    """The app's Wowhead client."""
    client: httpx.AsyncClient = state[WOWHEAD_STATE_KEY]
    return client


async def item_look(client: httpx.AsyncClient, item_id: int) -> ItemLook | None:
    """The item's look from Wowhead, cached process-wide. ``None`` if Wowhead has no such item or no model for it.

    A failed request is not cached, so the next character page asks again.
    """
    if item_id in _item_looks:
        return _item_looks[item_id]
    async with _lookup_semaphore:
        try:
            response = await client.get(ITEM_XML_URL.format(item_id=item_id))
        except httpx.HTTPError:
            return None
    if response.status_code != httpx.codes.OK:
        return None
    display = _DISPLAY_ID.search(response.text)
    inventory = _INVENTORY_TYPE.search(response.text)
    look = ItemLook(int(display[1]), int(inventory[1])) if display and inventory and display[1] != "0" else None
    _item_looks[item_id] = look
    return look


async def open_model_file(client: httpx.AsyncClient, path: str) -> httpx.Response:
    """Start streaming one of the viewer's files from Wowhead. The caller reads the body and closes the response.

    ``path`` must already match ``MODEL_FILE_PATH``. Raises ``httpx.HTTPError`` if Wowhead can't be reached.
    """
    request = client.build_request("GET", MODEL_FILES_URL + path, headers={"Accept-Encoding": "identity"})
    return await client.send(request, stream=True)
