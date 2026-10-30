"""EPGP loot system: the addon import, public standings/ledger/loot/progression, and officer admin.

``MyCharactersController`` (``/api/me/characters``) lives here too since it shares ``EpgpService`` and the
``WowCharacter`` model with the rest of the domain.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from litestar import Controller, delete, get, post, put
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, FromQuery, JSONBody, QueryParameter

from sidequest_api.domain.calendar.dependencies import provide_calendar_service
from sidequest_api.domain.calendar.services import CalendarService
from sidequest_api.domain.epgp.dependencies import provide_epgp_service, provide_import_actor, provide_sync_token_row
from sidequest_api.domain.epgp.services import EpgpService
from sidequest_api.lib.member_auth import provide_optional_member
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
    tags = ["EPGP"]
    dependencies = {
        "epgp_service": Provide(provide_epgp_service),
        "optional_member": Provide(provide_optional_member),
        "import_actor": Provide(provide_import_actor),
        "sync_token_row": Provide(provide_sync_token_row),
        "calendar_service": Provide(provide_calendar_service),
    }

    @post("/imports", operation_id="ImportEpgpPayload", status_code=200)
    async def import_payload(
        self,
        data: JSONBody[EpgpImportBody],
        import_actor: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpImportResult:
        """Decode and upsert one ``SQX1:`` export string (officer session, or a valid Bearer sync token).

        401 missing/invalid/revoked auth, 403 a valid token's member lost officer access, 400 a bad export string.
        """
        return await epgp_service.import_payload(data.payload, import_actor)

    @get("/standings", operation_id="GetEpgpStandings")
    async def get_standings(self, epgp_service: NamedDependency[EpgpService]) -> EpgpStandings:
        """Decayed-on-read EP/GP standings, highest PR first (public)."""
        return await epgp_service.get_standings()

    @get("/ledger", operation_id="GetEpgpLedger")
    async def get_ledger(
        self,
        epgp_service: NamedDependency[EpgpService],
        member_id: FromQuery[int | None] = None,
        character: FromQuery[str | None] = None,
        limit: Annotated[int, QueryParameter(ge=1, le=MAX_LEDGER_LIMIT)] = DEFAULT_LEDGER_LIMIT,
        before: FromQuery[datetime | None] = None,
    ) -> EpgpLedgerPage:
        """Ledger entries newest first (public)."""
        return await epgp_service.get_ledger(member_id=member_id, character=character, limit=limit, before=before)

    @get("/loot", operation_id="GetEpgpLoot")
    async def get_loot(
        self,
        epgp_service: NamedDependency[EpgpService],
        limit: Annotated[int, QueryParameter(ge=1, le=MAX_LOOT_LIMIT)] = DEFAULT_LOOT_LIMIT,
    ) -> EpgpLootPage:
        """Loot awards newest first (public)."""
        return await epgp_service.get_loot(limit=limit)

    @get("/progression", operation_id="GetEpgpProgression")
    async def get_progression(self, epgp_service: NamedDependency[EpgpService]) -> EpgpProgression:
        """Kill/wipe tallies per boss, grouped by instance (public)."""
        return await epgp_service.get_progression()

    @get("/game-import", operation_id="GetEpgpGameImport")
    async def get_game_import(
        self, import_actor: NamedDependency[Member], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpGameImport:
        """The ``SQI1:`` string for ``/sq import`` (officer session, or a valid Bearer sync token).

        401 missing/invalid/revoked auth, 403 a valid token's member lost officer access.
        """
        del import_actor
        return await epgp_service.build_game_import()

    @post("/adjustments", operation_id="CreateEpgpAdjustment", status_code=201)
    async def create_adjustment(
        self,
        data: JSONBody[EpgpAdjustmentCreate],
        current_officer: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpLedgerRow:
        """A site-made EP/GP ledger entry (officer). 401/403 non-officer, 404 unknown member."""
        return await epgp_service.create_adjustment(data, current_officer)

    @get("/characters", operation_id="ListEpgpCharacters")
    async def list_characters(
        self, current_officer: NamedDependency[Member], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpCharacterList:
        """Every known character, officer admin view. 401/403 non-officer."""
        del current_officer
        return await epgp_service.list_characters()

    @put("/characters/{character_id:uuid}", operation_id="UpdateEpgpCharacter")
    async def update_character(
        self,
        character_id: FromPath[UUID],
        data: JSONBody[EpgpCharacterUpdate],
        current_officer: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpCharacter:
        """Relink or mark a character as the member's main (officer). 401/403 non-officer, 404 unknown character."""
        del current_officer
        return await epgp_service.update_character(character_id, data)

    @get("/roster", operation_id="GetEpgpRoster")
    async def get_roster(
        self, current_officer: NamedDependency[Member], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpRoster:
        """Guild members' EPGP roster status (officer). 401/403 non-officer."""
        del current_officer
        return await epgp_service.list_roster()

    @put("/roster/{member_id:int}", operation_id="UpdateEpgpRoster")
    async def update_roster(
        self,
        member_id: FromPath[int],
        data: JSONBody[EpgpRosterUpdate],
        current_officer: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpRosterRow:
        """Set a member's raid status; setting ``"trial"`` stamps ``trial_started_at`` now (officer).

        401/403 non-officer, 404 unknown member.
        """
        del current_officer
        return await epgp_service.update_roster(member_id, data)

    @get("/sync-tokens", operation_id="ListEpgpSyncTokens")
    async def list_sync_tokens(
        self, current_member: NamedDependency[Member], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpSyncTokenList:
        """The signed-in member's own non-revoked sync tokens. 401/403 non-member."""
        return await epgp_service.list_sync_tokens(current_member)

    @post("/sync-tokens", operation_id="CreateEpgpSyncToken", status_code=201)
    async def create_sync_token(
        self,
        data: JSONBody[EpgpSyncTokenCreate],
        current_officer: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpSyncTokenCreated:
        """Create a sync token; the plaintext is returned once and never stored (officer). 401/403 non-officer."""
        return await epgp_service.create_sync_token(current_officer, data)

    @get("/sync-tokens/me", operation_id="GetMySyncToken")
    async def get_my_sync_token(
        self,
        sync_token_row: NamedDependency[EpgpSyncToken],
        epgp_service: NamedDependency[EpgpService],
        calendar_service: NamedDependency[CalendarService],
        web_settings: NamedDependency[WebSettings],
    ) -> EpgpSyncTokenMe:
        """What the presenting Bearer sync token's owner can see about themselves (SideQuest Companion).

        401 missing/invalid/revoked token, 403 the owner is no longer a guild member.
        """
        return await epgp_service.get_sync_token_owner_profile(
            sync_token_row,
            officer_role_ids=web_settings.OFFICER_ROLE_IDS,
            calendar_service=calendar_service,
            base_url=web_settings.BASE_URL,
        )

    @delete("/sync-tokens/me", operation_id="RevokeMySyncToken", status_code=204)
    async def revoke_my_sync_token(
        self, sync_token_row: NamedDependency[EpgpSyncToken], epgp_service: NamedDependency[EpgpService]
    ) -> None:
        """Revoke the presenting Bearer sync token. 401 missing/invalid/already-revoked token."""
        await epgp_service.revoke_presented_sync_token(sync_token_row)

    @delete("/sync-tokens/{token_id:uuid}", operation_id="RevokeEpgpSyncToken", status_code=204)
    async def revoke_sync_token(
        self,
        token_id: FromPath[UUID],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> None:
        """Revoke one of the signed-in member's own sync tokens. 401/403 non-member, 404 unknown/not own token."""
        await epgp_service.revoke_sync_token(current_member, token_id)

    @post("/device-authorizations", operation_id="CreateEpgpDeviceAuthorization", status_code=201)
    async def create_device_authorization(
        self,
        data: JSONBody[EpgpDeviceAuthorizationCreate],
        epgp_service: NamedDependency[EpgpService],
        web_settings: NamedDependency[WebSettings],
    ) -> EpgpDeviceAuthorizationCreated:
        """Start a browser sign-in for SideQuest Companion (public). 429 too many pending sign-ins."""
        return await epgp_service.create_device_authorization(data, base_url=web_settings.BASE_URL)

    @post("/device-authorizations/token", operation_id="PollEpgpDeviceAuthorization", status_code=200)
    async def poll_device_authorization(
        self, data: JSONBody[EpgpDeviceAuthorizationPoll], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpDeviceAuthorizationPollResult:
        """Poll a device code for its sign-in status (public). Always 200, never an oracle."""
        return await epgp_service.poll_device_authorization(data)

    @get("/device-authorizations/{user_code:str}", operation_id="GetEpgpDeviceAuthorization")
    async def get_device_authorization(
        self,
        user_code: FromPath[str],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpDeviceAuthorizationStatus:
        """A pending device sign-in's status (any guild member). 401/403 non-member, 404 unknown code."""
        del current_member
        return await epgp_service.get_device_authorization(user_code)

    @post(
        "/device-authorizations/{user_code:str}/approve",
        operation_id="ApproveEpgpDeviceAuthorization",
        status_code=204,
    )
    async def approve_device_authorization(
        self,
        user_code: FromPath[str],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> None:
        """Approve a pending device sign-in (any guild member). 401/403 non-member, 404 unknown, 409 not pending."""
        await epgp_service.approve_device_authorization(current_member, user_code)

    @post("/device-authorizations/{user_code:str}/deny", operation_id="DenyEpgpDeviceAuthorization", status_code=204)
    async def deny_device_authorization(
        self,
        user_code: FromPath[str],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> None:
        """Deny a pending device sign-in (any guild member). 401/403 non-member, 404 unknown, 409 not pending."""
        del current_member
        await epgp_service.deny_device_authorization(user_code)


class MyCharactersController(Controller):
    """``/api/me/characters``: a signed-in member's own ``WowCharacter`` links."""

    path = "/api/me/characters"
    tags = ["EPGP"]
    dependencies = {"epgp_service": Provide(provide_epgp_service)}

    @get("/", operation_id="ListMyCharacters")
    async def list_my_characters(
        self, current_member: NamedDependency[Member], epgp_service: NamedDependency[EpgpService]
    ) -> EpgpCharacterList:
        """The signed-in member's own characters. 401 not signed in / 403 not a guild member."""
        return await epgp_service.list_my_characters(current_member)

    @post("/", operation_id="ClaimMyCharacter", status_code=201)
    async def claim_character(
        self,
        data: JSONBody[MyCharacterCreate],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> EpgpCharacter:
        """Self-claim a character by name (and optional realm/class). 409 if another member already claimed it."""
        return await epgp_service.claim_character(current_member, data)

    @delete("/{character_id:uuid}", operation_id="DeleteMyCharacter", status_code=204)
    async def delete_character(
        self,
        character_id: FromPath[UUID],
        current_member: NamedDependency[Member],
        epgp_service: NamedDependency[EpgpService],
    ) -> None:
        """Remove one of the signed-in member's own characters. 404 unknown/not own character."""
        await epgp_service.delete_my_character(current_member, character_id)
