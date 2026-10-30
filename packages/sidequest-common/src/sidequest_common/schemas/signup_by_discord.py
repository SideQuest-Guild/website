"""Bot-key sign-up lookup/upsert by Discord id, for Discord's Going/Maybe/Can't buttons.

``GET/PUT /api/guilds/{guild_id}/events/{event_id}/signups/by-discord/{discord_id}``: lets the bot read and write a
member's signup without a site session, identifying them by Discord id instead (same shape of trick as
``signup_notices``'s bot-key roster-confirmation routes).
"""

from pydantic import BaseModel, ConfigDict, Field

from sidequest_common.schemas.events import EventKind, Signup, SignupRole, WowClass


class SignupDefaults(BaseModel):
    """A member's most recent character/class/role from any earlier signup, to prefill a new one."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    character: str | None
    wow_class: WowClass | None = Field(alias="class")
    role: SignupRole | None


class SignupByDiscord(BaseModel):
    """``GET .../signups/by-discord/{discord_id}``: the member's current signup for this event, plus defaults.

    ``signup`` is ``None`` if the member hasn't signed up for this event yet. ``defaults`` is ``None`` if the
    member has never given character/class/role on any event. ``kind`` is the event's kind, so the bot can tell
    whether a bare RSVP is enough without a second round trip.
    """

    signup: Signup | None
    defaults: SignupDefaults | None
    kind: EventKind
