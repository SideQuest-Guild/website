"""Guild members who have signed in through Discord OAuth."""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import BigIntAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import BigInteger, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column


class Member(BigIntAuditBase):
    """One Discord user who has logged into the member hub.

    ``id`` is a small internal integer (the contract's ``Me.id``), distinct from ``discord_id`` (Discord's
    64-bit snowflake, carried as a string in JSON). ``username``/``global_name``/``roles``/``guild_nick``/
    ``avatar_hash``/``is_guild_member`` are refreshed from Discord both at sign-in and continuously by the bot
    (``PUT /api/guilds/{guild_id}/member-profiles``: a full sweep plus debounced pushes on Discord profile/role/
    membership changes), so they stay current even for a member who never signs in again after renaming.
    ``avatar_hash`` is Discord's raw avatar hash (``null`` for the default avatar); build the CDN URL from it
    rather than storing a URL that can go stale.

    ``battlenet_id``/``battletag`` are set when the member links Battle.net (one Battle.net account per member, so
    one Blizzard account can't vouch for several Discord accounts); officers compare the BattleTag to the roster.

    ``officer_notice_posted_at`` is when the bot posted the new-signup notice embed for this member in the
    configured signup-notice channel (``null`` until posted; existing members are backfilled non-null at migration
    so prod isn't flooded). ``officer_notice_channel_id``/``officer_notice_message_id`` locate that message so it
    can be edited later. ``officer_notice_resolved_at`` is set once the posted message accurately reflects the
    member's current roster status (approved via the embed's button, or edited after a site confirmation).
    """

    __tablename__ = "member"
    __table_args__ = {"comment": "Guild members who have signed in with Discord."}

    discord_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(Text)
    global_name: Mapped[str | None] = mapped_column(Text, default=None)
    guild_nick: Mapped[str | None] = mapped_column(Text, default=None)
    avatar_hash: Mapped[str | None] = mapped_column(Text, default=None)
    roles: Mapped[list[int]] = mapped_column(JsonB, default=list)
    is_guild_member: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    battlenet_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, default=None)
    battletag: Mapped[str | None] = mapped_column(Text, default=None)
    battlenet_linked_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    roster_confirmed_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    officer_notice_posted_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    officer_notice_resolved_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), default=None)
    officer_notice_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    officer_notice_message_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    calendar_token: Mapped[str | None] = mapped_column(Text, unique=True, default=None)
    """Secret token for the member's private calendar feed (``GET /api/calendar/{token}.ics``); generated lazily."""

    @property
    def display_name(self) -> str:
        """Guild nick, else Discord global name, else username."""
        return self.guild_nick or self.global_name or self.username
