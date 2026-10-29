"""Officer/GM action audit trail: write one row to the request's session alongside the change it records.

Bot/Discord-originated changes are never audited here (no officer/GM actor); see ``local://gm-console-contract.md``.
Committed immediately rather than left for the request's closing autocommit, so it never gets picked up by a later
unrelated autoflush (which would otherwise interleave a write with whatever query triggered the flush).
"""

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_common.models import Member, OfficerAudit


async def record_officer_audit(
    session: AsyncSession, *, actor: Member, action: str, subject_type: str, subject_id: str | None, summary: str
) -> None:
    """Write an ``OfficerAudit`` row for ``actor``'s action to ``session`` and commit it."""
    session.add(
        OfficerAudit(
            actor_member_id=actor.id,
            actor_name=actor.display_name,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            summary=summary,
        )
    )
    await session.commit()
