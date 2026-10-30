"""Addon endpoints: public read, officer manage. Files are hosted elsewhere; we only store links."""

from typing import Annotated
from uuid import UUID

from litestar import Controller, delete, get, patch, post
from litestar.di import NamedDependency, Provide
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import JSONBody, Parameter

from sidequest_api.domain.addons.dependencies import provide_addons_service
from sidequest_api.domain.addons.services import AddonsService
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_api.lib.openapi import NOT_AN_OFFICER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import AddonCreate, AddonSchema, AddonUpdate

_ADDON_ID = Annotated[UUID, Parameter(description="The addon's ID.")]


class AddonsController(Controller):
    """``/api/addons``."""

    path = "/api/addons"
    dependencies = {"addons_service": Provide(provide_addons_service)}

    @get(
        "/",
        operation_id="ListAddons",
        tags=["Addons"],
        summary="List addons",
        description="Returns every recommended addon, sorted by name.",
        response_description="The addons.",
    )
    async def list_addons(self, addons_service: NamedDependency[AddonsService]) -> list[AddonSchema]:
        addons = await addons_service.list_sorted()
        return [AddonSchema.model_validate(addon) for addon in addons]

    @post(
        "/",
        operation_id="CreateAddon",
        status_code=201,
        tags=["Addon catalog"],
        security=SECURITY_SESSION,
        summary="Add an addon",
        description="Adds a recommended addon. An officer must be signed in.",
        response_description="The newly created addon.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            409: ResponseSpec(None, description="An addon with that slug already exists."),
        },
    )
    async def create_addon(
        self,
        data: JSONBody[AddonCreate],
        addons_service: NamedDependency[AddonsService],
        current_officer: NamedDependency[Member],
    ) -> AddonSchema:
        addon = await addons_service.create_addon(data)
        await record_officer_audit(
            addons_service.repository.session,
            actor=current_officer,
            action="addon.create",
            subject_type="addon",
            subject_id=str(addon.id),
            summary=f'Added addon "{addon.name}"',
        )
        return AddonSchema.model_validate(addon)

    @patch(
        "/{addon_id:uuid}",
        operation_id="UpdateAddon",
        tags=["Addon catalog"],
        security=SECURITY_SESSION,
        summary="Edit an addon",
        description="Edits an addon. An officer must be signed in.",
        response_description="The updated addon.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="No addon with that ID."),
        },
    )
    async def update_addon(
        self,
        addon_id: _ADDON_ID,
        data: JSONBody[AddonUpdate],
        addons_service: NamedDependency[AddonsService],
        current_officer: NamedDependency[Member],
    ) -> AddonSchema:
        addon = await addons_service.update_addon(addon_id, data)
        await record_officer_audit(
            addons_service.repository.session,
            actor=current_officer,
            action="addon.update",
            subject_type="addon",
            subject_id=str(addon.id),
            summary=f'Updated addon "{addon.name}"',
        )
        return AddonSchema.model_validate(addon)

    @delete(
        "/{addon_id:uuid}",
        operation_id="DeleteAddon",
        tags=["Addon catalog"],
        security=SECURITY_SESSION,
        summary="Remove an addon",
        description="Removes an addon. An officer must be signed in.",
        response_description="The addon was removed.",
        responses={
            401: NOT_SIGNED_IN,
            403: NOT_AN_OFFICER,
            404: ResponseSpec(None, description="No addon with that ID."),
        },
    )
    async def delete_addon(
        self,
        addon_id: _ADDON_ID,
        addons_service: NamedDependency[AddonsService],
        current_officer: NamedDependency[Member],
    ) -> None:
        addon = await addons_service.get_addon_or_404(addon_id)
        await addons_service.delete_addon(addon_id)
        await record_officer_audit(
            addons_service.repository.session,
            actor=current_officer,
            action="addon.delete",
            subject_type="addon",
            subject_id=str(addon_id),
            summary=f'Removed addon "{addon.name}"',
        )
