"""Character endpoints: public lookups, the bot's roster sync, and the officers' raid readiness setting.

``GET /api/characters/{slug}`` and ``GET /api/characters/boards`` are the same for every visitor and have no query
string, so Cloudflare may keep them at the edge for a few minutes. Search answers differ by query string, which
Cloudflare's cache rule ignores, so search is never edge-cached; it reads only Postgres.
"""

from typing import Annotated

from litestar import Controller, get, post, put
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter
from wow import AsyncClient

from sidequest_api.domain.characters.dependencies import provide_characters_service
from sidequest_api.domain.characters.services import CharactersService, to_page, to_summary
from sidequest_api.domain.guilds.dependencies import provide_guild_config_service
from sidequest_api.domain.guilds.services import GuildConfigService
from sidequest_api.lib.game_data import provide_game_data
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION, GuildIdPath
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import (
    CHARACTER_SEARCH_MIN_LENGTH,
    CHARACTER_SLUG_MAX_LENGTH,
    CharacterPage,
    CharacterSummary,
    HeroBoards,
    RaidReadinessSettings,
    RosterSyncReport,
)
from sidequest_common.settings import WebSettings

# A character changes as it is played: ten minutes at the edge, then stale for an hour while one fetch refreshes it.
EDGE_CHARACTER_CACHE = ResponseHeader(name=EDGE_CACHE_HEADER, value="max-age=600, stale-while-revalidate=3600")
# ``name-surname``: two parts and nothing that would leave the path segment.
_SLUG = r"^[^\s/?#-]+-[^\s/?#-]+$"
_NOT_SITE_GUILD = ResponseSpec(None, description="This guild_id is not the SideQuest server.")


class CharactersController(Controller):
    """``/api/characters``."""

    path = "/api/characters"
    tags = ["Characters"]
    dependencies = {"characters_service": Provide(provide_characters_service), "game_data": Provide(provide_game_data)}

    @get(
        "/",
        operation_id="SearchCharacters",
        opt=SKIP_SESSION,
        summary="Search characters",
        description=(
            "Without `q`, returns the guild roster from its last sync with Battle.net, highest rank first. With `q`, "
            "returns up to 25 stored characters (the roster and anyone looked up before) whose name and surname "
            "contain `q`, roster first. Battle.net has no name search: look anyone else up by their exact name "
            "and surname with Get a character."
        ),
        response_description="The matching characters.",
    )
    async def search(
        self,
        characters_service: NamedDependency[CharactersService],
        q: Annotated[
            str | None,
            Parameter(
                description="Text to find in names and surnames.", min_length=CHARACTER_SEARCH_MIN_LENGTH, max_length=60
            ),
        ] = None,
    ) -> list[CharacterSummary]:
        query = q.strip() if q is not None else None
        rank_names = await characters_service.rank_names()
        return [to_summary(row, rank_names) for row in await characters_service.search(query or None)]

    @get(
        "/boards",
        operation_id="GetHeroBoards",
        response_headers=[EDGE_CHARACTER_CACHE],
        opt=SKIP_SESSION,
        summary="Get the hero boards",
        description=(
            "Returns the guild roster's top ten characters by equipped item level, honorable kills, PvP rank and "
            "achievement points, from their Battle.net profiles. Characters without a profile yet are left out."
        ),
        response_description="The four boards.",
    )
    async def boards(self, characters_service: NamedDependency[CharactersService]) -> HeroBoards:
        return await characters_service.hero_boards()

    @get(
        "/{slug:str}",
        operation_id="GetCharacter",
        response_headers=[EDGE_CHARACTER_CACHE],
        opt=SKIP_SESSION,
        summary="Get a character",
        description=(
            "Returns one character by its `name-surname` slug, in any case: its summary and character sheet (gear, "
            "stats, talents, professions, reputations, recent achievements and collections). The first lookup stores "
            "the character, and it is fetched again from Battle.net when its copy is six hours old. Answers 404 if "
            "Battle.net has no such character; Battle.net publishes a character some time after it logs out. Answers "
            "503 if Battle.net is not configured, or did not answer and the character was never stored."
        ),
        response_description="The character and its sheet.",
    )
    async def get_character(
        self,
        characters_service: NamedDependency[CharactersService],
        game_data: NamedDependency[AsyncClient],
        slug: Annotated[
            str,
            Parameter(
                description="The character's name and surname joined by a hyphen, such as `nox-zul`.",
                max_length=CHARACTER_SLUG_MAX_LENGTH,
                pattern=_SLUG,
            ),
        ],
    ) -> CharacterPage:
        character = await characters_service.get_character(slug.casefold(), game_data)
        return to_page(character, await characters_service.rank_names())


class RosterSyncController(Controller):
    """``/api/guilds/{guild_id}/characters``: the bot's roster sync."""

    path = "/characters"
    tags = ["Roster sync"]
    dependencies = {"characters_service": Provide(provide_characters_service), "game_data": Provide(provide_game_data)}

    @post(
        "/sync",
        operation_id="SyncRoster",
        status_code=200,
        summary="Sync the roster from Battle.net",
        description=(
            "Reads the guild roster from Battle.net: stores new members, marks members who left, updates ranks and "
            "levels, matches addon characters to their Battle.net characters by name, and refreshes up to eight "
            "character profiles older than six hours, roster first. Safe to call repeatedly. Returns 404 for any "
            "guild_id other than the SideQuest server, and 503 if Battle.net is not configured or did not answer."
        ),
        response_description="What the sync changed.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def sync(
        self,
        guild_id: GuildIdPath,
        characters_service: NamedDependency[CharactersService],
        game_data: NamedDependency[AsyncClient],
        web_settings: NamedDependency[WebSettings],
    ) -> RosterSyncReport:
        if guild_id != web_settings.GUILD_ID:
            msg = f"No guild {guild_id}"
            raise NotFoundException(msg)
        return await characters_service.sync_roster(game_data)


class RaidReadinessController(Controller):
    """``/api/raid-readiness``: the officers' minimum item level for raids."""

    path = "/api/raid-readiness"
    tags = ["Raid readiness"]
    security = SECURITY_SESSION
    dependencies = {"guild_config_service": Provide(provide_guild_config_service)}

    @put(
        "/",
        operation_id="SetRaidReadiness",
        summary="Set the minimum item level",
        description=(
            "Sets the equipped item level below which raid sign-ups are marked on the raid chart, or clears it with "
            "`null`. An officer must be signed in."
        ),
        response_description="The saved setting.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def set_readiness(
        self,
        data: JSONBody[RaidReadinessSettings],
        current_officer: NamedDependency[Member],
        guild_config_service: NamedDependency[GuildConfigService],
        web_settings: NamedDependency[WebSettings],
    ) -> RaidReadinessSettings:
        config = await guild_config_service.get_or_create_config(web_settings.GUILD_ID)
        config.raid_min_item_level = data.min_item_level
        await guild_config_service.update(config, auto_commit=True)
        shown = data.min_item_level if data.min_item_level is not None else "none"
        await record_officer_audit(
            guild_config_service.repository.session,
            actor=current_officer,
            action="raid_readiness.update",
            subject_type="guild_config",
            subject_id=None,
            summary=f"Set the raid minimum item level to {shown}",
        )
        return RaidReadinessSettings(min_item_level=config.raid_min_item_level)
