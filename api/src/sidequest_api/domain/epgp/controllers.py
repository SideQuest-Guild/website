"""EPGP loot system: the addon import, public standings/ledger/loot/progression, and officer admin.

``MyCharactersController`` (``/api/me/characters``) lives here too since it shares ``EpgpService`` and the
``WowCharacter`` model with the rest of the domain.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from litestar import Controller, delete, get, post, put
from litestar.di import NamedDependency, Provide
from litestar.params import JSONBody, Parameter, QueryParameter

from sidequest_api.domain.calendar.dependencies import provide_calendar_service
from sidequest_api.domain.calendar.services import CalendarService
from sidequest_api.domain.epgp.dependencies import provide_epgp_service, provide_import_actor, provide_sync_token_row
from sidequest_api.domain.epgp.services import EpgpService
from sidequest_api.lib.member_auth import provide_optional_member
from sidequest_api.lib.openapi import (
    BAD_SYNC_OR_SESSION,
    NOT_A_MEMBER,
    NOT_AN_OFFICER,
    NOT_SIGNED_IN,
    SECURITY_SESSION,
    SECURITY_SESSION_OR_SYNC_TOKEN,
    SECURITY_SYNC_TOKEN,
    ResponseSpec,
)
from sidequest_common.models import EpgpSyncToken, Member
from sidequest_common.schemas import (
    EpgpAdjustmentCreate,
    EpgpCharacter,
    EpgpCharacterList,
    EpgpCharacterUpdate,
    EpgpDeviceAuthorizationCreate,
    EpgpDeviceAuthorizationCreated,
    EpgpDeviceAuthorizationPoll,
    EpgpDeviceAuthorizationPollResult,
    EpgpDeviceAuthorizationStatus,
    EpgpGameImport,
    EpgpImportBody,
    EpgpImportResult,
    EpgpLedgerPage,
    EpgpLedgerRow,
    EpgpLootPage,
    EpgpProgression,
    EpgpRoster,
    EpgpRosterRow,
    EpgpRosterUpdate,
    EpgpStandings,
    EpgpSyncTokenCreate,
    EpgpSyncTokenCreated,
    EpgpSyncTokenList,
    EpgpSyncTokenMe,
    MyCharacterCreate,
)
from sidequest_common.settings import WebSettings

DEFAULT_LEDGER_LIMIT = 50
MAX_LEDGER_LIMIT = 200
DEFAULT_LOOT_LIMIT = 50
MAX_LOOT_LIMIT = 200


class EpgpController(Controller):
    """``/api/epgp``: addon import, public standings/ledger/loot/progression, and officer admin."""

    path = "/api/epgp"
    dependencies = {
        "epgp_service": Provide(provide_epgp_service),
        "optional_member": Provide(provide_optional_member),
        "import_actor": Provide(provide_import_actor),
        "sync_token_row": Provide(provide_sync_token_row),
        "calendar_service": Provide(provide_calendar_service),
    }

    @post(
        "/imports",
        operation_id="ImportEpgpPayload",
        status_code=200,
        tags=["EPGP import"],
        security=SECURITY_SESSION_OR_SYNC_TOKEN,
        summary="Import an addon EPGP export",
        description=(
            "Decodes and upserts one `SQX1:` export string from the addon. An officer session or a valid "
            "Bearer sync token works."
        ),
        response_description="A summary of the rows the import created or updated.",
        responses={
            401: BAD_SYNC_OR_SESSION,
            403: ResponseSpec(None, description="The sync token's officer lost officer access."),
            400: ResponseSpec(None, description="The `SQX1:` export string is missing or not valid."),
        },
    )
    async def import_payload(
        self,
        data: JSONBody[EpgpImportBody],
        import_actor: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpImportResult:
        return await epgp_service.import_payload(data.payload, import_actor)

    @get(
        "/standings",
        operation_id="GetEpgpStandings",
        tags=["Loot ledger"],
        summary="Get SQL standings",
        description="Returns decayed-on-read EP/GP standings, highest PR first.",
        response_description="The SQL (SideQuest Loot) standings.",
    )
    async def get_standings(self, epgp_service: NamedDependency[EpgpService]) -> EpgpStandings:
        return await epgp_service.get_standings()

    @get(
        "/ledger",
        operation_id="GetEpgpLedger",
        tags=["Loot ledger"],
        summary="Get the SQL ledger",
        description="Returns SQL (SideQuest Loot) ledger entries, newest first.",
        response_description="A page of ledger entries.",
    )
    async def get_ledger(
        self,
        epgp_service: NamedDependency[EpgpService],
        member_id: Annotated[int | None, Parameter(description="Only return entries for this member.")] = None,
        character: Annotated[str | None, Parameter(description="Only return entries for this character name.")] = (
            None
        ),
        limit: Annotated[int, QueryParameter(ge=1, le=MAX_LEDGER_LIMIT, description="Max entries to return.")] = (
            DEFAULT_LEDGER_LIMIT
        ),
        before: Annotated[datetime | None, Parameter(description="Only return entries before this time.")] = None,
    ) -> EpgpLedgerPage:
        return await epgp_service.get_ledger(member_id=member_id, character=character, limit=limit, before=before)

    @get(
        "/loot",
        operation_id="GetEpgpLoot",
        tags=["Loot ledger"],
        summary="Get loot awards",
        description="Returns loot awards, newest first.",
        response_description="A page of loot awards.",
    )
    async def get_loot(
        self,
        epgp_service: NamedDependency[EpgpService],
        limit: Annotated[int, QueryParameter(ge=1, le=MAX_LOOT_LIMIT, description="Max awards to return.")] = (
            DEFAULT_LOOT_LIMIT
        ),
    ) -> EpgpLootPage:
        return await epgp_service.get_loot(limit=limit)

    @get(
        "/progression",
        operation_id="GetEpgpProgression",
        tags=["Loot ledger"],
        summary="Get boss progression",
        description="Returns kill and wipe tallies per boss, grouped by instance.",
        response_description="The boss progression.",
    )
    async def get_progression(self, epgp_service: NamedDependency[EpgpService]) -> EpgpProgression:
        return await epgp_service.get_progression()

    @get(
        "/game-import",
        operation_id="GetEpgpGameImport",
        tags=["Loot administration"],
        security=SECURITY_SESSION_OR_SYNC_TOKEN,
        summary="Get the addon game-import string",
        description=(
            "Returns the `SQI1:` string for the addon's `/sq import` command. An officer session or a valid Bearer "
            "sync token works."
        ),
        response_description="The game-import payload.",
        responses={
            401: BAD_SYNC_OR_SESSION,
            403: ResponseSpec(None, description="The sync token's owner lost officer access."),
        },
    )
    async def get_game_import(
        self, import_actor: NamedDependency[Member], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpGameImport:
        del import_actor
        return await epgp_service.build_game_import()

    @post(
        "/adjustments",
        operation_id="CreateEpgpAdjustment",
        status_code=201,
        tags=["Loot administration"],
        security=SECURITY_SESSION,
        summary="Create an EP/GP adjustment",
        description="Creates a site-made EP/GP ledger entry attributed to the signed-in officer.",
        response_description="The new ledger entry.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="Unknown member."),
        },
    )
    async def create_adjustment(
        self,
        data: JSONBody[EpgpAdjustmentCreate],
        current_officer: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpLedgerRow:
        return await epgp_service.create_adjustment(data, current_officer)

    @get(
        "/characters",
        operation_id="ListEpgpCharacters",
        tags=["Loot administration"],
        security=SECURITY_SESSION,
        summary="List characters",
        description="Returns every known character, the officer admin view.",
        response_description="The characters.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def list_characters(
        self, current_officer: NamedDependency[Member], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpCharacterList:
        del current_officer
        return await epgp_service.list_characters()

    @put(
        "/characters/{character_id:uuid}",
        operation_id="UpdateEpgpCharacter",
        tags=["Loot administration"],
        security=SECURITY_SESSION,
        summary="Relink a character",
        description="Relinks a character to a member, or marks it as that member's main.",
        response_description="The updated character.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="Unknown character."),
        },
    )
    async def update_character(
        self,
        character_id: Annotated[UUID, Parameter(description="The character's ID.")],
        data: JSONBody[EpgpCharacterUpdate],
        current_officer: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpCharacter:
        del current_officer
        return await epgp_service.update_character(character_id, data)

    @get(
        "/roster",
        operation_id="GetEpgpRoster",
        tags=["Loot administration"],
        security=SECURITY_SESSION,
        summary="Get the EPGP roster",
        description="Returns guild members' EPGP roster status.",
        response_description="The roster.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def get_roster(
        self, current_officer: NamedDependency[Member], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpRoster:
        del current_officer
        return await epgp_service.list_roster()

    @put(
        "/roster/{member_id:int}",
        operation_id="UpdateEpgpRoster",
        tags=["Loot administration"],
        security=SECURITY_SESSION,
        summary="Set a member's raid status",
        description=(
            "Sets a member's raid status. Setting it to `trial` stamps `trial_started_at` with the current time."
        ),
        response_description="The updated roster row.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="Unknown member."),
        },
    )
    async def update_roster(
        self,
        member_id: Annotated[int, Parameter(description="The member's ID.")],
        data: JSONBody[EpgpRosterUpdate],
        current_officer: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpRosterRow:
        del current_officer
        return await epgp_service.update_roster(member_id, data)

    @get(
        "/sync-tokens",
        operation_id="ListEpgpSyncTokens",
        tags=["SideQuest Companion"],
        security=SECURITY_SESSION,
        summary="List my sync tokens",
        description="Returns the signed-in member's own sync tokens that are not revoked.",
        response_description="The sync tokens.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def list_sync_tokens(
        self, current_member: NamedDependency[Member], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpSyncTokenList:
        return await epgp_service.list_sync_tokens(current_member)

    @post(
        "/sync-tokens",
        operation_id="CreateEpgpSyncToken",
        status_code=201,
        tags=["Sync tokens"],
        security=SECURITY_SESSION,
        summary="Create a sync token",
        description="Creates a sync token for the signed-in officer. The plaintext is returned once and never stored.",
        response_description="The created sync token, with its plaintext value.",
        responses={401: NOT_SIGNED_IN, 403: NOT_AN_OFFICER},
    )
    async def create_sync_token(
        self,
        data: JSONBody[EpgpSyncTokenCreate],
        current_officer: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpSyncTokenCreated:
        return await epgp_service.create_sync_token(current_officer, data)

    @get(
        "/sync-tokens/me",
        operation_id="GetMySyncToken",
        tags=["SideQuest Companion"],
        security=SECURITY_SYNC_TOKEN,
        summary="Get the sync token owner's profile",
        description="Returns what the Bearer sync token's owner can see about themselves, for SideQuest Companion.",
        response_description="The token owner's profile.",
        responses={
            401: ResponseSpec(None, description="The sync token is missing, wrong, or revoked."),
            403: ResponseSpec(None, description="The token's owner is no longer a guild member."),
        },
    )
    async def get_my_sync_token(
        self,
        sync_token_row: NamedDependency[EpgpSyncToken],
        epgp_service: NamedDependency[EpgpService],
        calendar_service: NamedDependency[CalendarService],
        web_settings: NamedDependency[WebSettings],
    ) -> EpgpSyncTokenMe:
        return await epgp_service.get_sync_token_owner_profile(
            sync_token_row,
            officer_role_ids=web_settings.OFFICER_ROLE_IDS,
            calendar_service=calendar_service,
            base_url=web_settings.BASE_URL,
        )

    @delete(
        "/sync-tokens/me",
        operation_id="RevokeMySyncToken",
        status_code=204,
        tags=["SideQuest Companion"],
        security=SECURITY_SYNC_TOKEN,
        summary="Revoke this sync token",
        description="Revokes the Bearer sync token sent with the request, so SideQuest Companion can sign out.",
        response_description="The sync token was revoked.",
        responses={401: ResponseSpec(None, description="The sync token is missing, wrong, or already revoked.")},
    )
    async def revoke_my_sync_token(
        self, sync_token_row: NamedDependency[EpgpSyncToken], epgp_service: NamedDependency[EpgpService]
    ) -> None:
        await epgp_service.revoke_presented_sync_token(sync_token_row)

    @delete(
        "/sync-tokens/{token_id:uuid}",
        operation_id="RevokeEpgpSyncToken",
        status_code=204,
        tags=["SideQuest Companion"],
        security=SECURITY_SESSION,
        summary="Revoke one of my sync tokens",
        description="Revokes one of the signed-in member's own sync tokens.",
        response_description="The sync token was revoked.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            404: ResponseSpec(None, description="Unknown sync token, or it is not yours."),
        },
    )
    async def revoke_sync_token(
        self,
        token_id: Annotated[UUID, Parameter(description="The sync token's ID.")],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> None:
        await epgp_service.revoke_sync_token(current_member, token_id)

    @post(
        "/device-authorizations",
        operation_id="CreateEpgpDeviceAuthorization",
        status_code=201,
        tags=["SideQuest Companion"],
        summary="Start a companion sign-in",
        description=(
            "Starts a browser sign-in for SideQuest Companion and returns a code to show the member. No sign-in needed."
        ),
        response_description="The device code, the code to show, and the page to open.",
        responses={429: ResponseSpec(None, description="Too many sign-ins are waiting.")},
    )
    async def create_device_authorization(
        self,
        data: JSONBody[EpgpDeviceAuthorizationCreate],
        epgp_service: NamedDependency[EpgpService],
        web_settings: NamedDependency[WebSettings],
    ) -> EpgpDeviceAuthorizationCreated:
        return await epgp_service.create_device_authorization(data, base_url=web_settings.BASE_URL)

    @post(
        "/device-authorizations/token",
        operation_id="PollEpgpDeviceAuthorization",
        status_code=200,
        tags=["SideQuest Companion"],
        summary="Check a companion sign-in",
        description=(
            "Returns whether a companion sign-in is still waiting, approved (with its sync token) or denied. Always "
            "200, so it never reveals whether a code exists."
        ),
        response_description="The sign-in's status.",
    )
    async def poll_device_authorization(
        self, data: JSONBody[EpgpDeviceAuthorizationPoll], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpDeviceAuthorizationPollResult:
        return await epgp_service.poll_device_authorization(data)

    @get(
        "/device-authorizations/{user_code:str}",
        operation_id="GetEpgpDeviceAuthorization",
        tags=["SideQuest Companion"],
        security=SECURITY_SESSION,
        summary="Get a companion sign-in",
        description="Returns a waiting companion sign-in, so the member can check it before approving.",
        response_description="The sign-in's status.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER, 404: ResponseSpec(None, description="Unknown code.")},
    )
    async def get_device_authorization(
        self,
        user_code: Annotated[str, Parameter(description="The code the companion shows.")],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpDeviceAuthorizationStatus:
        del current_member
        return await epgp_service.get_device_authorization(user_code)

    @post(
        "/device-authorizations/{user_code:str}/approve",
        operation_id="ApproveEpgpDeviceAuthorization",
        status_code=204,
        tags=["SideQuest Companion"],
        security=SECURITY_SESSION,
        summary="Approve a companion sign-in",
        description="Approves a waiting companion sign-in, which gives the companion a sync token for this member.",
        response_description="The sign-in was approved.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            404: ResponseSpec(None, description="Unknown code."),
            409: ResponseSpec(None, description="The sign-in is no longer waiting."),
        },
    )
    async def approve_device_authorization(
        self,
        user_code: Annotated[str, Parameter(description="The code the companion shows.")],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> None:
        await epgp_service.approve_device_authorization(current_member, user_code)

    @post(
        "/device-authorizations/{user_code:str}/deny",
        operation_id="DenyEpgpDeviceAuthorization",
        status_code=204,
        tags=["SideQuest Companion"],
        security=SECURITY_SESSION,
        summary="Deny a companion sign-in",
        description="Denies a waiting companion sign-in.",
        response_description="The sign-in was denied.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            404: ResponseSpec(None, description="Unknown code."),
            409: ResponseSpec(None, description="The sign-in is no longer waiting."),
        },
    )
    async def deny_device_authorization(
        self,
        user_code: Annotated[str, Parameter(description="The code the companion shows.")],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> None:
        del current_member
        await epgp_service.deny_device_authorization(user_code)


class MyCharactersController(Controller):
    """``/api/me/characters``: a signed-in member's own ``WowCharacter`` links."""

    path = "/api/me/characters"
    tags = ["My characters"]
    security = SECURITY_SESSION
    dependencies = {"epgp_service": Provide(provide_epgp_service)}

    @get(
        "/",
        operation_id="ListMyCharacters",
        summary="List my characters",
        description="Returns the signed-in member's own claimed characters.",
        response_description="The member's claimed characters.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def list_my_characters(
        self, current_member: NamedDependency[Member], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpCharacterList:
        return await epgp_service.list_my_characters(current_member)

    @post(
        "/",
        operation_id="ClaimMyCharacter",
        status_code=201,
        summary="Claim a character",
        description="Self-claims a character by name, with an optional realm and class.",
        response_description="The claimed character.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            409: ResponseSpec(None, description="Another member already claimed this character."),
        },
    )
    async def claim_character(
        self,
        data: JSONBody[MyCharacterCreate],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpCharacter:
        return await epgp_service.claim_character(current_member, data)

    @delete(
        "/{character_id:uuid}",
        operation_id="DeleteMyCharacter",
        status_code=204,
        summary="Remove a character",
        description="Removes one of the signed-in member's own characters.",
        response_description="The character was removed.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_A_MEMBER,
            404: ResponseSpec(None, description="The character does not exist or belongs to someone else."),
        },
    )
    async def delete_character(
        self,
        character_id: Annotated[UUID, Parameter(description="The character's ID.")],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> None:
        await epgp_service.delete_my_character(current_member, character_id)
