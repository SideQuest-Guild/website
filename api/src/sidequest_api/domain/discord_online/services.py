"""Fetches Discord's public server widget and trims it to what the homepage roster shows.

Cached in-process (module-level, per guild) for ``CACHE_TTL_SECONDS`` so a page of visitors costs Discord at most
one request a minute. The cache is intentionally process-local, not shared/edge: the endpoint is members-only and
must never be edge-cached (it varies by session).
"""

import logging
import time
from typing import Any

import httpx

from sidequest_common.schemas import DiscordOnline, DiscordOnlineMember

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
WIDGET_TIMEOUT_SECONDS = 3.0

# guild_id -> (fetched at, monotonic clock, result). Module-level: one cache per process, shared by every request.
_cache: dict[int, tuple[float, DiscordOnline]] = {}

_STATUS_ORDER = {"online": 0, "idle": 1, "dnd": 2}


def _activity_name(member: dict[str, Any]) -> str | None:
    """The member's activity/game name. Discord's widget uses ``activity``; ``game`` is an older alias."""
    for key in ("activity", "game"):
        value = member.get(key)
        if isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str) and name:
                return name
    return None


def _sort_key(member: DiscordOnlineMember) -> tuple[int, str]:
    return (_STATUS_ORDER.get(member.status, 99), member.name.casefold())


class DiscordOnlineService:
    """Fetches and trims ``GET /guilds/{id}/widget.json``, caching the result for ``CACHE_TTL_SECONDS``."""

    def __init__(self, discord_client: httpx.AsyncClient) -> None:
        self._discord_client = discord_client

    async def get_online(self, guild_id: int) -> DiscordOnline:
        """The guild's widget roster, from cache if fetched within the last ``CACHE_TTL_SECONDS``."""
        now = time.monotonic()
        cached = _cache.get(guild_id)
        if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        online = await self._fetch(guild_id)
        _cache[guild_id] = (now, online)
        return online

    async def _fetch(self, guild_id: int) -> DiscordOnline:
        try:
            response = await self._discord_client.get(f"/guilds/{guild_id}/widget.json", timeout=WIDGET_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError, ValueError:
            logger.warning("Discord widget fetch failed for guild %s", guild_id, exc_info=True)
            return DiscordOnline(presence_count=None, members=[], ok=False)
        members = sorted(
            (
                DiscordOnlineMember(
                    name=str(member.get("username", "")),
                    status=str(member.get("status", "online")),
                    avatar_url=member.get("avatar_url"),
                    activity=_activity_name(member),
                )
                for member in data.get("members", [])
                if isinstance(member, dict)
            ),
            key=_sort_key,
        )
        return DiscordOnline(presence_count=data.get("presence_count"), members=members, ok=True)
