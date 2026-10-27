from typing import TYPE_CHECKING, Any

import pytest

from sidequest_api.domain.guilds.services import GuildConfigService
from sidequest_common.models import GuildConfig
from tests.conftest import GUILD_ID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_first_access_race_returns_the_winning_row(
    db_sessionmaker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two requests both see no config; the loser's insert fails and it must recover with the winner's row."""
    async with db_sessionmaker() as winner_session, db_sessionmaker() as loser_session:
        loser = GuildConfigService(session=loser_session)
        real_lookup = loser.get_one_or_none

        async def lookup_then_lose_race(**kwargs: Any) -> GuildConfig | None:
            result = await real_lookup(**kwargs)
            # The other request inserts between our lookup and our insert.
            winner_session.add(GuildConfig(guild_id=GUILD_ID, xp_max=99))
            await winner_session.commit()
            return result

        monkeypatch.setattr(loser, "get_one_or_none", lookup_then_lose_race)
        config = await loser.get_or_create_config(GUILD_ID)

    assert config.xp_max == 99
