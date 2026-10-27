"""Addon persistence."""

from typing import TYPE_CHECKING

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_409_CONFLICT
from sqlalchemy import select

from sidequest_common.models import Addon

if TYPE_CHECKING:
    from uuid import UUID

    from sidequest_common.schemas import AddonCreate, AddonUpdate


class AddonsRepository(SQLAlchemyAsyncRepository[Addon]):
    """Addon persistence."""

    model_type = Addon


class AddonsService(SQLAlchemyAsyncRepositoryService[Addon]):
    """Recommended addons, sorted by name for listing."""

    repository_type = AddonsRepository

    async def list_sorted(self) -> list[Addon]:
        """All addons, sorted by name."""
        session = self.repository.session
        statement = select(Addon).order_by(Addon.name.asc())
        return list((await session.execute(statement)).scalars().all())

    async def get_addon_or_404(self, addon_id: UUID) -> Addon:
        """The addon, or 404."""
        addon = await self.get_one_or_none(id=addon_id)
        if addon is None:
            msg = f"No addon {addon_id}"
            raise NotFoundException(msg)
        return addon

    async def create_addon(self, data: AddonCreate) -> Addon:
        """Create an addon. 409 if ``slug`` is already taken."""
        try:
            return await self.create(Addon(**data.model_dump()), auto_commit=True)
        except IntegrityError as exc:
            msg = f"An addon with slug {data.slug!r} already exists"
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg) from exc

    async def update_addon(self, addon_id: UUID, data: AddonUpdate) -> Addon:
        """Apply the present fields of ``data`` to the addon."""
        addon = await self.get_addon_or_404(addon_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(addon, field, value)
        return await self.update(addon, auto_commit=True)

    async def delete_addon(self, addon_id: UUID) -> None:
        """Delete an addon."""
        await self.get_addon_or_404(addon_id)
        await self.delete(addon_id, auto_commit=True)
