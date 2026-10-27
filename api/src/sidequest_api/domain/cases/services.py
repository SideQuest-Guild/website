"""Moderation case service."""

from typing import TYPE_CHECKING

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import HTTPException, NotFoundException
from sqlalchemy import func, select

from sidequest_common.models import ModCase

if TYPE_CHECKING:
    from sidequest_common.schemas import ModCaseCreate, ModCaseUpdate

MAX_CASE_NUMBER_RETRIES = 5


class CasesRepository(SQLAlchemyAsyncRepository[ModCase]):
    """ModCase persistence."""

    model_type = ModCase


class CasesService(SQLAlchemyAsyncRepositoryService[ModCase]):
    """Records and queries moderation cases, assigning sequential per-guild case numbers."""

    repository_type = CasesRepository

    async def create_case(self, guild_id: int, data: ModCaseCreate) -> ModCase:
        """Record a new case. Retries the number assignment if a concurrent writer wins the race."""
        for _ in range(MAX_CASE_NUMBER_RETRIES):
            case_number = await self._next_case_number(guild_id)
            case = ModCase(guild_id=guild_id, case_number=case_number, **data.model_dump())
            try:
                return await self.create(case, auto_commit=True)
            except IntegrityError:
                await self.repository.session.rollback()
                continue
        msg = "Could not assign a case number; too many concurrent writers"
        raise HTTPException(status_code=409, detail=msg)

    async def _next_case_number(self, guild_id: int) -> int:
        session = self.repository.session
        result = await session.execute(select(func.max(ModCase.case_number)).where(ModCase.guild_id == guild_id))
        current_max = result.scalar()
        return (current_max or 0) + 1

    async def list_cases(
        self, guild_id: int, *, user_id: int | None = None, limit: int = 25, offset: int = 0
    ) -> list[ModCase]:
        """Cases for ``guild_id``, newest first, optionally only for ``user_id``."""
        session = self.repository.session
        statement = select(ModCase).where(ModCase.guild_id == guild_id)
        if user_id is not None:
            statement = statement.where(ModCase.user_id == user_id)
        statement = statement.order_by(ModCase.case_number.desc()).limit(limit).offset(offset)
        return list((await session.execute(statement)).scalars().all())

    async def get_case(self, guild_id: int, case_number: int) -> ModCase:
        """One case; raises NotFoundException if it doesn't exist."""
        case = await self.get_one_or_none(guild_id=guild_id, case_number=case_number)
        if case is None:
            msg = f"No case #{case_number} in guild {guild_id}"
            raise NotFoundException(msg)
        return case

    async def update_case(self, guild_id: int, case_number: int, data: ModCaseUpdate) -> ModCase:
        """Apply the fields present in ``data`` (currently just ``reason``)."""
        case = await self.get_case(guild_id, case_number)
        changes = data.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(case, field, value)
        return await self.update(case, auto_commit=True)
