"""Character endpoints: public lookups, the bot's roster sync, and the officers' raid readiness setting.

``GET /api/characters/{slug}`` and ``GET /api/characters/boards`` are the same for every visitor and have no query
string, so Cloudflare may keep them at the edge for a few minutes. Search answers differ by query string, which
Cloudflare's cache rule ignores, so search is never edge-cached; it reads only Postgres.
"""

from typing import Annotated
from uuid import UUID

import httpx
from litestar import Controller, get, post, put
from litestar.background_tasks import BackgroundTask
from litestar.datastructures import ResponseHeader
from litestar.di import NamedDependency, Provide
from litestar.exceptions import HTTPException, NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter, PathParameter
from litestar.response import Stream
from litestar.status_codes import HTTP_502_BAD_GATEWAY, HTTP_503_SERVICE_UNAVAILABLE
from wow import AsyncClient, NotFoundError, WowError

from sidequest_api.domain.characters.dependencies import provide_characters_service
from sidequest_api.domain.characters.model_viewer import build_character_model
from sidequest_api.domain.characters.services import BATTLENET_UNREACHABLE, CharactersService, to_page, to_summary
from sidequest_api.domain.guilds.dependencies import provide_guild_config_service
from sidequest_api.domain.guilds.services import GuildConfigService
from sidequest_api.lib.game_data import provide_game_data
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION, GuildIdPath
from sidequest_api.lib.website import EDGE_CACHE_HEADER, SKIP_SESSION
from sidequest_api.lib.wowhead import MODEL_FILE_PATH, open_model_file, provide_wowhead
from sidequest_common.models import Member
from sidequest_common.schemas import (
    CHARACTER_SEARCH_MIN_LENGTH,
    CHARACTER_SLUG_MAX_LENGTH,
    CHARACTER_SLUG_PATTERN,
    CharacterMilestoneSchema,
    CharacterModel,
    CharacterPage,
    CharacterSummary,
    HeroBoards,
    MilestonePosted,
    RaidReadinessSettings,
    RosterSyncReport,
)
from sidequest_common.settings import WebSettings

# A character changes as it is played: ten minutes at the edge, then stale for an hour while one fetch refreshes it.
EDGE_CHARACTER_CACHE = ResponseHeader(name=EDGE_CACHE_HEADER, value="max-age=600, stale-while-revalidate=3600")
# The viewer's files only change with a game patch: a week in the browser, and a month at the edge once Cloudflare's
# cache rule lists /api/modelviewer/ (it doesn't yet, so for now every first view is relayed from Wowhead).
MODEL_FILE_BROWSER_CACHE = "public, max-age=604800"
MODEL_FILE_EDGE_CACHE = "max-age=2592000"
# The body is relayed as Wowhead sent it, so its encoding and length headers travel with it.
_MODEL_FILE_HEADERS = ("content-encoding", "content-length", "etag", "last-modified")
WOWHEAD_UNREACHABLE = "Wowhead did not answer; try again in a minute"
_NOT_SITE_GUILD = ResponseSpec(None, description="This guild_id is not the SideQuest server.")


def _require_site_guild(guild_id: int, web_settings: WebSettings) -> None:
    if guild_id != web_settings.GUILD_ID:
        msg = f"No guild {guild_id}"
        raise NotFoundException(msg)


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
        "/milestones",
        operation_id="ListCharacterMilestones",
        response_headers=[EDGE_CHARACTER_CACHE],
        opt=SKIP_SESSION,
        summary="List recent level milestones",
        description=(
            "Returns the latest 20 times a guild roster character reached level 40 or 60, newest first, as the "
            "roster sync saw them. The bot posts each one to Discord."
        ),
        response_description="The recent milestones.",
    )
    async def milestones(
        self, characters_service: NamedDependency[CharactersService]
    ) -> list[CharacterMilestoneSchema]:
        return [CharacterMilestoneSchema.model_validate(row) for row in await characters_service.recent_milestones()]

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
                pattern=CHARACTER_SLUG_PATTERN,
            ),
        ],
    ) -> CharacterPage:
        character = await characters_service.get_character(slug.casefold(), game_data)
        return to_page(character, await characters_service.rank_names())

    @get(
        "/{slug:str}/model",
        operation_id="GetCharacterModel",
        dependencies={"wowhead": Provide(provide_wowhead)},
        response_headers=[EDGE_CHARACTER_CACHE],
        opt=SKIP_SESSION,
        summary="Get a character's 3D model",
        description=(
            "Returns what Wowhead's model viewer needs to draw the character as Battle.net last published it: its "
            "race and body model, barber choices, and worn items by display id. The character page's View in 3D "
            "button draws it, with the model files from Get a 3D model file. Items Wowhead has no look for are left "
            "out. Answers 404 if Battle.net has no such character, or none of a race the viewer covers, and 503 if "
            "Battle.net is not configured or did not answer."
        ),
        response_description="The model viewer's options for the character.",
    )
    async def get_character_model(
        self,
        game_data: NamedDependency[AsyncClient],
        wowhead: NamedDependency[httpx.AsyncClient],
        slug: Annotated[
            str,
            Parameter(
                description="The character's name and surname joined by a hyphen, such as `nox-zul`.",
                max_length=CHARACTER_SLUG_MAX_LENGTH,
                pattern=CHARACTER_SLUG_PATTERN,
            ),
        ],
    ) -> CharacterModel:
        try:
            appearance = await game_data.characters.appearance(slug.casefold())
        except NotFoundError as exc:
            msg = f"Battle.net has no appearance for {slug}"
            raise NotFoundException(msg) from exc
        except WowError as exc:
            raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
        model = await build_character_model(appearance, wowhead)
        if model is None:
            msg = f"The model viewer can't draw {slug}'s race"
            raise NotFoundException(msg)
        return model


class ModelViewerController(Controller):
    """``/api/modelviewer``: Wowhead's model viewer files, relayed for the character page's 3D model."""

    path = "/api/modelviewer"
    tags = ["Characters"]
    dependencies = {"wowhead": Provide(provide_wowhead)}

    @get(
        "/{file_path:path}",
        operation_id="GetModelViewerFile",
        opt=SKIP_SESSION,
        summary="Get a 3D model file",
        description=(
            "Relays one of Wowhead's WoW: Forever model viewer files (models, textures and their descriptions, such "
            "as `meta/armor/5/8071.json` or `m2/959310.m2`). Wowhead serves them only to its own pages, so the "
            "character page's viewer reads them from here. Answers 404 for a path that isn't a viewer file or that "
            "Wowhead doesn't have, and 502 if Wowhead did not answer."
        ),
        response_description="The file, as Wowhead serves it.",
    )
    async def get_file(
        self,
        wowhead: NamedDependency[httpx.AsyncClient],
        file_path: Annotated[str, PathParameter(description="The file's path under the viewer's files.")],
    ) -> Stream:
        path = file_path.removeprefix("/")
        if MODEL_FILE_PATH.fullmatch(path) is None:
            msg = "Not a model viewer file"
            raise NotFoundException(msg)
        try:
            upstream = await open_model_file(wowhead, path)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=HTTP_502_BAD_GATEWAY, detail=WOWHEAD_UNREACHABLE) from exc
        if upstream.status_code != httpx.codes.OK:
            await upstream.aclose()
            if upstream.status_code == httpx.codes.NOT_FOUND:
                msg = "Wowhead has no such model viewer file"
                raise NotFoundException(msg)
            raise HTTPException(status_code=HTTP_502_BAD_GATEWAY, detail=WOWHEAD_UNREACHABLE)
        headers = {name: upstream.headers[name] for name in _MODEL_FILE_HEADERS if name in upstream.headers}
        headers["cache-control"] = MODEL_FILE_BROWSER_CACHE
        headers[EDGE_CACHE_HEADER] = MODEL_FILE_EDGE_CACHE
        return Stream(
            upstream.aiter_raw(),
            media_type=upstream.headers.get("content-type", "application/octet-stream"),
            headers=headers,
            background=BackgroundTask(upstream.aclose),
        )


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
        _require_site_guild(guild_id, web_settings)
        return await characters_service.sync_roster(game_data)

    @get(
        "/milestones/pending",
        operation_id="ListPendingMilestones",
        summary="List milestones to post",
        description=(
            "Returns the level 40 and 60 milestones the bot has not posted to Discord yet, oldest first. Returns "
            "404 for any guild_id other than the SideQuest server."
        ),
        response_description="The milestones still to post.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def pending_milestones(
        self,
        guild_id: GuildIdPath,
        characters_service: NamedDependency[CharactersService],
        web_settings: NamedDependency[WebSettings],
    ) -> list[CharacterMilestoneSchema]:
        _require_site_guild(guild_id, web_settings)
        return [CharacterMilestoneSchema.model_validate(row) for row in await characters_service.pending_milestones()]

    @post(
        "/milestones/{milestone_id:uuid}/posted",
        operation_id="MarkMilestonePosted",
        status_code=204,
        summary="Mark a milestone as posted",
        description=(
            "Records that the bot posted a milestone to Discord, so it stops coming back as pending. Returns 404 for "
            "an unknown milestone, or any guild_id other than the SideQuest server."
        ),
        response_description="The milestone is marked as posted.",
        responses={404: _NOT_SITE_GUILD},
    )
    async def mark_posted(
        self,
        guild_id: GuildIdPath,
        milestone_id: Annotated[UUID, Parameter(description="The milestone's ID.")],
        data: JSONBody[MilestonePosted],
        characters_service: NamedDependency[CharactersService],
        web_settings: NamedDependency[WebSettings],
    ) -> None:
        _require_site_guild(guild_id, web_settings)
        await characters_service.mark_milestone_posted(milestone_id, data.discord_message_id)


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
