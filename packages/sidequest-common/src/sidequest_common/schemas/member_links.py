"""Member link status, reported to the bot for role syncing."""

from pydantic import BaseModel


class MemberLink(BaseModel):
    """One known member's link status (``GET /api/guilds/{guild_id}/member-links``), bot-facing.

    ``discord_id`` is an ``int`` here (unlike the public ``Me`` schema, which carries it as a string): this
    route is bot-key only and the bot already works with Discord ids as integers.

    ``signed_in`` is false for a member a Quest Master confirmed from Discord who has never signed in on the site.
    """

    discord_id: int
    battlenet_linked: bool
    # Defaulted so a bot newer than the API still parses (same reasoning as GuildConfigSchema's role ids).
    roster_confirmed: bool = False
    signed_in: bool = True
    # In-game guild rank names held by the member's characters on the Battle.net guild roster, best rank first
    # (several when their characters hold different ranks). ``guild_ranks`` counts every character linked to them;
    # ``battlenet_guild_ranks`` only those their linked Battle.net account owns. Empty when none is on the roster.
    guild_ranks: list[str] = []
    battlenet_guild_ranks: list[str] = []
    # Their characters on the Battle.net guild roster ("Name Surname"), the one that joined the guild first leading.
    guild_characters: list[str] = []
    # Whether the bot has made its one nickname call (set it to guild_characters[0], or left an existing one). True
    # by default, so a bot newer than the API never renames anyone.
    character_nick_done: bool = True
