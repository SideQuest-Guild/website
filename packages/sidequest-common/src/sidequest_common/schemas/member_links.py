"""Member link status, reported to the bot for role syncing."""

from pydantic import BaseModel


class MemberLink(BaseModel):
    """One signed-in member's link status (``GET /api/guilds/{guild_id}/member-links``), bot-facing.

    ``discord_id`` is an ``int`` here (unlike the public ``Me`` schema, which carries it as a string): this
    route is bot-key only and the bot already works with Discord ids as integers.
    """

    discord_id: int
    battlenet_linked: bool
    # Defaulted so a bot newer than the API still parses (same reasoning as GuildConfigSchema's role ids).
    roster_confirmed: bool = False
