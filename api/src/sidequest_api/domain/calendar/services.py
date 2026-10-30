"""Calendar token issuance and the events shown on a member's private feed."""

import secrets
from datetime import UTC, datetime, timedelta

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from sqlalchemy import select

from sidequest_common.models import EventSignup, GuildEvent, Member

TOKEN_BYTES = 24
"""``secrets.token_urlsafe(24)`` carries 192 bits of entropy, well over the 128-bit floor."""

FEED_LOOKBACK = timedelta(days=30)


class CalendarRepository(SQLAlchemyAsyncRepository[Member]):
    """Member persistence for calendar token issuance and feed token lookups."""

    model_type = Member


class CalendarService(SQLAlchemyAsyncRepositoryService[Member]):
    """Issues/rotates a member's private calendar token, resolves a feed token, and lists a member's feed events."""

    repository_type = CalendarRepository

    async def get_or_create_token(self, member: Member) -> str:
        """The member's calendar token, generating one the first time it's asked for."""
        if member.calendar_token is not None:
            return member.calendar_token
        return await self._assign_new_token(member)

    async def rotate_token(self, member: Member) -> str:
        """Replace the member's token with a new one; the old link 404s from the moment this returns."""
        return await self._assign_new_token(member)

    async def _assign_new_token(self, member: Member) -> str:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        member.calendar_token = token
        await self.update(member, auto_commit=True)
        return token

    async def get_by_token(self, token: str) -> Member | None:
        """The member this feed token belongs to, or ``None`` if it's unknown (never issued, or since rotated)."""
        return await self.get_one_or_none(calendar_token=token)

    async def list_feed_events(
        self, member: Member, *, now: datetime | None = None
    ) -> list[tuple[GuildEvent, EventSignup | None]]:
        """Guild events from 30 days before ``now`` onward, each paired with the member's own signup, if any."""
        now = now or datetime.now(UTC)
        session = self.repository.session
        cutoff = now - FEED_LOOKBACK
        events = list(
            (
                await session.execute(
                    select(GuildEvent).where(GuildEvent.starts_at >= cutoff).order_by(GuildEvent.starts_at)
                )
            ).scalars()
        )
        if not events:
            return []
        event_ids = [event.id for event in events]
        signups_by_event = {
            signup.event_id: signup
            for signup in (
                await session.execute(
                    select(EventSignup).where(EventSignup.event_id.in_(event_ids), EventSignup.member_id == member.id)
                )
            ).scalars()
        }
        return [(event, signups_by_event.get(event.id)) for event in events]
