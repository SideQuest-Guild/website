"""Addon endpoints: public read, officer manage. Files are hosted elsewhere; we only store links."""

from uuid import UUID

from litestar import Controller, delete, get, patch, post
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, JSONBody

from sidequest_api.domain.addons.dependencies import provide_addons_service
from sidequest_api.domain.addons.services import AddonsService
from sidequest_common.models import Member
from sidequest_common.schemas import AddonCreate, AddonSchema, AddonUpdate


class AddonsController(Controller):
    """``/api/addons``."""

    path = "/api/addons"
    tags = ["Addons"]
    dependencies = {"addons_service": Provide(provide_addons_service)}

    @get("/", operation_id="ListAddons")
    async def list_addons(self, addons_service: NamedDependency[AddonsService]) -> list[AddonSchema]:
        """All addons, sorted by name."""
        addons = await addons_service.list_sorted()
        return [AddonSchema.model_validate(addon) for addon in addons]

    @post("/", operation_id="CreateAddon", status_code=201)
    async def create_addon(
        self,
        data: JSONBody[AddonCreate],
        addons_service: NamedDependency[AddonsService],
        current_officer: NamedDependency[Member],
    ) -> AddonSchema:
        """Add a recommended addon (officer). 409 if ``slug`` is already taken."""
        del current_officer
        addon = await addons_service.create_addon(data)
        return AddonSchema.model_validate(addon)

    @patch("/{addon_id:uuid}", operation_id="UpdateAddon")
    async def update_addon(
        self,
        addon_id: FromPath[UUID],
        data: JSONBody[AddonUpdate],
        addons_service: NamedDependency[AddonsService],
        current_officer: NamedDependency[Member],
    ) -> AddonSchema:
        """Edit an addon (officer)."""
        del current_officer
        addon = await addons_service.update_addon(addon_id, data)
        return AddonSchema.model_validate(addon)

    @delete("/{addon_id:uuid}", operation_id="DeleteAddon")
    async def delete_addon(
        self,
        addon_id: FromPath[UUID],
        addons_service: NamedDependency[AddonsService],
        current_officer: NamedDependency[Member],
    ) -> None:
        """Remove an addon (officer)."""
        del current_officer
        await addons_service.delete_addon(addon_id)
