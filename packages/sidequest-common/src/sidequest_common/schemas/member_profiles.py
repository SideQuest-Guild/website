"""Member profile push, bot-key only: keeps names/roles/avatar synced with Discord continuously, not just at sign-in."""

from pydantic import BaseModel


class MemberProfileIn(BaseModel):
    """One member's current Discord profile, as reported by the bot.

    Mirrors the fields ``MembersService.upsert_from_discord`` sets at sign-in: ``avatar_hash`` is the user's main
    avatar hash (not a per-guild avatar), ``guild_nick``/``roles`` are this guild's nick/role ids.
    """

    discord_id: int
    username: str
    global_name: str | None
    guild_nick: str | None
    avatar_hash: str | None
    roles: list[int]


class MemberProfilesReplace(BaseModel):
    """Body for ``PUT /api/guilds/{guild_id}/member-profiles``.

    ``profiles`` are linked members currently in the guild; ``departed_ids`` are linked members no longer in the
    guild. Only existing ``Member`` rows are ever touched, never created: unknown ids are ignored.
    """

    profiles: list[MemberProfileIn]
    departed_ids: list[int]
