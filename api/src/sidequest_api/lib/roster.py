"""Shared ``Member`` roster-confirmation field mutations.

Plain mutations only (no session/commit): ``MembersService.confirm_roster``/``unconfirm_roster`` call these for
every officer-driven confirmation, and ``CharactersService.sync_roster`` calls ``confirm_roster`` directly for the
Battle.net auto-confirm sweep, where importing ``MembersService`` would create a circular import (``members``
already imports from ``characters``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sidequest_common.models import Member


def confirm_roster(member: Member, *, via: str) -> None:
    """Mark ``member`` confirmed on the in-game guild roster. Idempotent: keeps the first confirmation time.

    ``via`` is ``"officer"`` or ``"battlenet"`` (see ``Member.roster_confirmed_via``). An officer confirmation
    clears a prior removal; a Battle.net auto-confirmation never runs while one is set (the caller checks first).
    """
    if member.roster_confirmed_at is None:
        member.roster_confirmed_at = datetime.now(UTC)
    member.roster_confirmed_via = via
    if via == "officer":
        member.roster_removed_at = None


def unconfirm_roster(member: Member) -> None:
    """Clear ``member``'s roster confirmation and mark it officer-removed.

    Blocks auto-confirmation until an officer confirms them again.
    """
    member.roster_confirmed_at = None
    member.roster_confirmed_via = None
    member.roster_removed_at = datetime.now(UTC)
