"""Reads and replaces the guild's recruiting needs, treating a missing row as empty."""

from typing import TYPE_CHECKING

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService

from sidequest_common.models import RecruitingNeeds
from sidequest_common.schemas import Recruiting, RecruitingClassWant, RecruitingRoleWant

if TYPE_CHECKING:
    from sidequest_common.schemas import RecruitingUpdate


class RecruitingRepository(SQLAlchemyAsyncRepository[RecruitingNeeds]):
    """RecruitingNeeds persistence."""

    model_type = RecruitingNeeds


class RecruitingService(SQLAlchemyAsyncRepositoryService[RecruitingNeeds]):
    """Reads the guild's recruiting needs (empty if never set) and replaces them wholesale for officers."""

    repository_type = RecruitingRepository
    match_fields = ["guild_id"]

    async def get_needs(self, guild_id: int) -> Recruiting:
        """The guild's current recruiting needs, or empty lists if nothing has ever been set."""
        row = await self.get_one_or_none(guild_id=guild_id)
        if row is None:
            return Recruiting(roles=[], classes=[], updated_at=None)
        return Recruiting(
            roles=[RecruitingRoleWant.model_validate(want) for want in row.roles],
            classes=[RecruitingClassWant.model_validate(want) for want in row.classes],
            updated_at=row.updated_at,
        )

    async def replace_needs(self, guild_id: int, data: RecruitingUpdate) -> Recruiting:
        """Replace the guild's full set of wanted roles and classes."""
        roles = [want.model_dump(mode="json") for want in data.roles]
        classes = [want.model_dump(mode="json") for want in data.classes]
        existing = await self.get_one_or_none(guild_id=guild_id)
        if existing is None:
            try:
                row = await self.create(
                    RecruitingNeeds(guild_id=guild_id, roles=roles, classes=classes), auto_commit=True
                )
            except IntegrityError:
                # Another request created it between our read and insert. The failed flush poisons the session's
                # transaction, so roll back before reading the winner's row.
                await self.repository.session.rollback()
                existing = await self.get_one(guild_id=guild_id)
                existing.roles = roles
                existing.classes = classes
                row = await self.update(existing, auto_commit=True)
        else:
            existing.roles = roles
            existing.classes = classes
            row = await self.update(existing, auto_commit=True)
        return Recruiting(
            roles=[RecruitingRoleWant.model_validate(want) for want in row.roles],
            classes=[RecruitingClassWant.model_validate(want) for want in row.classes],
            updated_at=row.updated_at,
        )
