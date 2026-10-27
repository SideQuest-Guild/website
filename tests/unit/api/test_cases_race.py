from typing import TYPE_CHECKING

import pytest

from sidequest_api.domain.cases.services import CasesService
from sidequest_common.models import ModCase
from sidequest_common.schemas import CaseAction, ModCaseCreate
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_concurrent_case_creation_recovers_from_a_number_collision(
    db_sessionmaker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another request inserts the same next case number between our lookup and our insert.

    Without a session rollback after the resulting IntegrityError, the next read on the same session raises
    ``PendingRollbackError`` instead of retrying, and concurrent case creation fails outright.
    """
    async with db_sessionmaker() as winner_session, db_sessionmaker() as loser_session:
        loser = CasesService(session=loser_session)
        real_next_case_number = loser._next_case_number
        race_already_happened = False

        async def next_case_number_then_lose_race_once(guild_id: int) -> int:
            nonlocal race_already_happened
            number = await real_next_case_number(guild_id)
            if not race_already_happened:
                race_already_happened = True
                winner_session.add(
                    ModCase(guild_id=guild_id, case_number=number, action=CaseAction.WARN, user_id=1, moderator_id=2)
                )
                await winner_session.commit()
            return number

        monkeypatch.setattr(loser, "_next_case_number", next_case_number_then_lose_race_once)
        case = await loser.create_case(GUILD_ID, ModCaseCreate(action=CaseAction.WARN, user_id=3, moderator_id=4))

    assert case.case_number == 2
