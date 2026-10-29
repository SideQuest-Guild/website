"""Discord role-reset outbox, reported to the bot so it can strip a deleted account's Discord roles.

The bot polls ``GET /api/guilds/{guild_id}/role-resets`` for members whose site account was deleted and still
need every manageable Discord role stripped (gate role excepted, since ``link_roles`` re-grants it once the
member is unlinked). ``POST .../role-resets/{id}/ack`` tells the API the bot has acted (or that the member is no
longer in the guild, in which case it's acked without any role changes).
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RoleResetCandidate(BaseModel):
    """One pending role reset, oldest first."""

    id: UUID
    discord_id: int
    requested_at: datetime
