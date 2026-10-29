"""New-signup officer notice outbox, and bot-key roster confirmation by Discord id.

The bot polls ``GET /api/guilds/{guild_id}/signup-notices`` for members it hasn't posted a notice embed for yet
(``pending``), and for already-posted notices whose embed is stale because the member was confirmed on the site
since (``resolved``: needs its message edited to say so). ``POST .../signup-notices/{member_id}/ack`` tells the API
the bot's message now accurately reflects the member's state, for both cases.
"""

from datetime import datetime

from pydantic import BaseModel


class SignupNoticeCandidate(BaseModel):
    """One member who has never had a signup notice posted for them, oldest first."""

    member_id: int
    discord_id: str
    display_name: str
    username: str
    avatar_hash: str | None
    battletag: str | None
    roster_confirmed: bool
    created_at: datetime


class SignupNoticeResolution(BaseModel):
    """One posted notice whose message no longer reflects the member's state (confirmed since, e.g. on the site)."""

    member_id: int
    discord_id: str
    display_name: str
    channel_id: str
    message_id: str
    confirmed_by: str | None
    """The GM's display name as recorded in ``officer_audit`` for the confirmation, if found."""


class SignupNoticesPage(BaseModel):
    """API -> bot: what the signup-notices poll should act on this tick."""

    pending: list[SignupNoticeCandidate]
    resolved: list[SignupNoticeResolution]


class SignupNoticeAck(BaseModel):
    """Bot -> API: the notice message for this member now accurately reflects their current state."""

    channel_id: int
    message_id: int


class ConfirmByDiscordRequest(BaseModel):
    """Bot -> API: a Discord user (identified by snowflake) is taking a roster-confirmation action.

    ``actor_name`` is the clicking user's live Discord display name, used as the ``officer_audit`` actor snapshot
    only if ``actor_discord_id`` has no ``Member`` row of its own (defensive fallback; the GM gate itself requires
    a ``Member`` row with a configured GM role, so this normally isn't reached).
    """

    actor_discord_id: str
    actor_name: str
