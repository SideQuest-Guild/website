"""Read models and mutations behind the GM console.

Not an ``advanced_alchemy`` repository service: it spans several tables (members, signups, cases, officer audit,
levels, guild roles) rather than owning one. See ``local://gm-console-contract.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from litestar.exceptions import NotFoundException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from sidequest_api.lib.discord import avatar_url
from sidequest_api.lib.member_auth import is_gm, is_officer
from sidequest_common.models import (
    EventSignup,
    EventSignupActivity,
    GuildEvent,
    GuildRole,
    Member,
    MemberLevel,
    ModCase,
    OfficerAudit,
)
from sidequest_common.schemas import GmCase, GmMember, GmMemberDetail, GmSignup, LogActor, LogEntry, LogPage, RoleTag

if TYPE_CHECKING:
    from datetime import datetime

    from sidequest_common.settings import WebSettings

LOG_KINDS = ("signup", "sign_in", "battlenet", "officer", "moderation")

_SIGNUP_ACTION_PHRASES = {
    "going": "is going to",
    "maybe": "might make it to",
    "not_going": "can't make it to",
    "withdrew": "withdrew from",
}
_CASE_ACTION_VERBS = {
    "warn": "warned",
    "timeout": "timed out",
    "untimeout": "removed the timeout for",
    "kick": "kicked",
    "ban": "banned",
    "unban": "unbanned",
    "automod": "auto-moderated",
}


def _role_tag(role: GuildRole) -> RoleTag:
    return RoleTag(id=str(role.role_id), name=role.name, color=f"#{role.color:06x}" if role.color else None)


def _officer_subject_refs(audit: OfficerAudit) -> tuple[int | None, UUID | None, int | None]:
    """``(member_id, event_id, case_number)`` deep-link hints derived from the audit row's subject, when parseable."""
    if audit.subject_id is None:
        return None, None, None
    try:
        if audit.subject_type == "member":
            return int(audit.subject_id), None, None
        if audit.subject_type == "event":
            return None, UUID(audit.subject_id), None
        if audit.subject_type == "case":
            return None, None, int(audit.subject_id)
    except ValueError:
        return None, None, None
    return None, None, None


class GmService:
    """Everything the GM console reads or writes."""

    def __init__(self, session: AsyncSession, web_settings: WebSettings) -> None:
        self._session = session
        self._web_settings = web_settings

    @property
    def session(self) -> AsyncSession:
        """The request's session, for callers (e.g. the ``case.edit`` audit write) that need it directly."""
        return self._session

    # --- Shared lookups ----------------------------------------------------------------------------------------

    async def _roles_by_id(self) -> dict[int, GuildRole]:
        statement = select(GuildRole).where(
            GuildRole.guild_id == self._web_settings.GUILD_ID, GuildRole.managed.is_(False)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return {role.role_id: role for role in rows}

    def _member_role_tags(self, member: Member, roles_by_id: dict[int, GuildRole]) -> list[RoleTag]:
        tagged = sorted(
            (roles_by_id[role_id] for role_id in member.roles if role_id in roles_by_id),
            key=lambda role: role.position,
            reverse=True,
        )
        return [_role_tag(role) for role in tagged]

    async def _levels_by_user(self, user_ids: list[int]) -> dict[int, MemberLevel]:
        if not user_ids:
            return {}
        statement = select(MemberLevel).where(
            MemberLevel.guild_id == self._web_settings.GUILD_ID, MemberLevel.user_id.in_(user_ids)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return {level.user_id: level for level in rows}

    async def _signup_counts(self, member_ids: list[int]) -> dict[int, int]:
        if not member_ids:
            return {}
        statement = (
            select(EventSignup.member_id, func.count())
            .where(EventSignup.member_id.in_(member_ids))
            .group_by(EventSignup.member_id)
        )
        return dict((await self._session.execute(statement)).tuples().all())

    async def _case_counts(self, discord_ids: list[int]) -> dict[int, int]:
        if not discord_ids:
            return {}
        statement = (
            select(ModCase.user_id, func.count())
            .where(ModCase.guild_id == self._web_settings.GUILD_ID, ModCase.user_id.in_(discord_ids))
            .group_by(ModCase.user_id)
        )
        return dict((await self._session.execute(statement)).tuples().all())

    async def _members_by_discord(self, discord_ids: list[int]) -> dict[int, Member]:
        if not discord_ids:
            return {}
        statement = select(Member).where(Member.discord_id.in_(discord_ids))
        rows = (await self._session.execute(statement)).scalars().all()
        return {member.discord_id: member for member in rows}

    async def _members_by_id(self, member_ids: list[int]) -> dict[int, Member]:
        if not member_ids:
            return {}
        statement = select(Member).where(Member.id.in_(member_ids))
        rows = (await self._session.execute(statement)).scalars().all()
        return {member.id: member for member in rows}

    def _to_gm_member(
        self,
        member: Member,
        *,
        roles_by_id: dict[int, GuildRole],
        level: MemberLevel | None,
        signup_count: int,
        case_count: int,
    ) -> GmMember:
        return GmMember(
            id=member.id,
            discord_id=str(member.discord_id),
            username=member.username,
            display_name=member.display_name,
            avatar_url=avatar_url(member.discord_id, member.avatar_hash),
            roles=self._member_role_tags(member, roles_by_id),
            is_guild_member=member.is_guild_member,
            is_officer=is_officer(member, self._web_settings.OFFICER_ROLE_IDS),
            is_gm=is_gm(member, self._web_settings.GM_ROLE_IDS),
            roster_confirmed_at=member.roster_confirmed_at,
            battletag=member.battletag,
            battlenet_linked_at=member.battlenet_linked_at,
            first_seen_at=member.created_at,
            last_login_at=member.last_login_at,
            signup_count=signup_count,
            case_count=case_count,
            level=level.level if level is not None else None,
        )

    # --- Members -------------------------------------------------------------------------------------------------

    async def list_members(self) -> list[GmMember]:
        """Every signed-in member, Discord members first, then display name (casefold)."""
        members = list((await self._session.execute(select(Member))).scalars().all())
        members.sort(key=lambda m: (not m.is_guild_member, m.display_name.casefold()))
        roles_by_id = await self._roles_by_id()
        levels = await self._levels_by_user([member.discord_id for member in members])
        signup_counts = await self._signup_counts([member.id for member in members])
        case_counts = await self._case_counts([member.discord_id for member in members])
        return [
            self._to_gm_member(
                member,
                roles_by_id=roles_by_id,
                level=levels.get(member.discord_id),
                signup_count=signup_counts.get(member.id, 0),
                case_count=case_counts.get(member.discord_id, 0),
            )
            for member in members
        ]

    async def get_member_detail(self, member_id: int) -> GmMemberDetail:
        """A member's profile, signups (newest event first), and cases (newest first). 404 unknown member."""
        member = await self._session.get(Member, member_id)
        if member is None:
            msg = f"No member {member_id}"
            raise NotFoundException(msg)
        roles_by_id = await self._roles_by_id()
        level = (await self._levels_by_user([member.discord_id])).get(member.discord_id)
        signup_count = (await self._signup_counts([member.id])).get(member.id, 0)
        case_count = (await self._case_counts([member.discord_id])).get(member.discord_id, 0)
        gm_member = self._to_gm_member(
            member, roles_by_id=roles_by_id, level=level, signup_count=signup_count, case_count=case_count
        )
        signups = await self._signups_for(member.id)
        cases = await self.list_cases(user_id=member.discord_id)
        return GmMemberDetail(
            member=gm_member,
            signups=signups,
            cases=cases,
            xp=level.xp if level is not None else None,
            message_count=level.message_count if level is not None else None,
        )

    async def _signups_for(self, member_id: int) -> list[GmSignup]:
        statement = (
            select(EventSignup, GuildEvent)
            .join(GuildEvent, EventSignup.event_id == GuildEvent.id)
            .where(EventSignup.member_id == member_id)
            .order_by(GuildEvent.starts_at.desc())
        )
        rows = (await self._session.execute(statement)).all()
        return [
            GmSignup.model_validate(
                {
                    "event_id": event.id,
                    "title": event.title,
                    "kind": event.kind,
                    "starts_at": event.starts_at,
                    "event_status": event.status,
                    "status": signup.status,
                    "character": signup.character,
                    "class": signup.wow_class,
                    "role": signup.role,
                    "comment": signup.comment,
                }
            )
            for signup, event in rows
        ]

    # --- Cases ---------------------------------------------------------------------------------------------------

    async def list_cases(self, *, user_id: int | None = None) -> list[GmCase]:
        """Site-guild moderation cases, newest first, optionally only for ``user_id``."""
        statement = select(ModCase).where(ModCase.guild_id == self._web_settings.GUILD_ID)
        if user_id is not None:
            statement = statement.where(ModCase.user_id == user_id)
        statement = statement.order_by(ModCase.case_number.desc())
        cases = list((await self._session.execute(statement)).scalars().all())
        return await self._to_gm_cases(cases)

    async def _to_gm_cases(self, cases: list[ModCase]) -> list[GmCase]:
        discord_ids = list({case.user_id for case in cases} | {case.moderator_id for case in cases})
        members = await self._members_by_discord(discord_ids)
        return [
            GmCase(
                case_number=case.case_number,
                action=case.action,
                user_id=str(case.user_id),
                user_name=members[case.user_id].display_name if case.user_id in members else None,
                moderator_id=str(case.moderator_id),
                moderator_name=members[case.moderator_id].display_name if case.moderator_id in members else None,
                reason=case.reason,
                duration_seconds=case.duration_seconds,
                created_at=case.created_at,
            )
            for case in cases
        ]

    async def _get_case_or_404(self, case_number: int) -> ModCase:
        statement = select(ModCase).where(
            ModCase.guild_id == self._web_settings.GUILD_ID, ModCase.case_number == case_number
        )
        case = (await self._session.execute(statement)).scalar_one_or_none()
        if case is None:
            msg = f"No case {case_number}"
            raise NotFoundException(msg)
        return case

    async def update_case_reason(self, case_number: int, reason: str) -> GmCase:
        """Edit a case's reason. 404 if ``case_number`` doesn't exist for the site guild."""
        case = await self._get_case_or_404(case_number)
        case.reason = reason
        return (await self._to_gm_cases([case]))[0]

    # --- Log -----------------------------------------------------------------------------------------------------

    async def get_log(self, *, kinds: list[str] | None, before: datetime | None, limit: int) -> LogPage:
        """Merge the 5 activity sources, newest first, strictly before ``before`` when given."""
        active_kinds = [kind for kind in kinds if kind in LOG_KINDS] if kinds else list(LOG_KINDS)
        entries: list[LogEntry] = []
        if "signup" in active_kinds:
            entries.extend(await self._signup_log(before=before, limit=limit))
        if "sign_in" in active_kinds:
            entries.extend(await self._sign_in_log(before=before, limit=limit))
        if "battlenet" in active_kinds:
            entries.extend(await self._battlenet_log(before=before, limit=limit))
        if "officer" in active_kinds:
            entries.extend(await self._officer_log(before=before, limit=limit))
        if "moderation" in active_kinds:
            entries.extend(await self._moderation_log(before=before, limit=limit))
        entries.sort(key=lambda entry: entry.at, reverse=True)
        page = entries[:limit]
        next_before = page[-1].at if len(page) == limit else None
        return LogPage(entries=page, next_before=next_before)

    async def _signup_log(self, *, before: datetime | None, limit: int) -> list[LogEntry]:
        statement = (
            select(EventSignupActivity, GuildEvent.title)
            .join(GuildEvent, EventSignupActivity.event_id == GuildEvent.id)
            .order_by(EventSignupActivity.created_at.desc())
            .limit(limit)
        )
        if before is not None:
            statement = statement.where(EventSignupActivity.created_at < before)
        rows = (await self._session.execute(statement)).all()
        discord_ids = [activity.discord_id for activity, _ in rows if activity.discord_id is not None]
        members = await self._members_by_discord(discord_ids)
        entries = []
        for activity, title in rows:
            member = members.get(activity.discord_id) if activity.discord_id is not None else None
            phrase = _SIGNUP_ACTION_PHRASES[activity.action]
            entries.append(
                LogEntry(
                    id=f"signup:{activity.id}",
                    at=activity.created_at,
                    kind="signup",
                    actor=None,
                    summary=f"{activity.display_name} {phrase} {title}",
                    detail=activity.comment,
                    member_id=member.id if member is not None else None,
                    event_id=activity.event_id,
                    case_number=None,
                )
            )
        return entries

    async def _sign_in_log(self, *, before: datetime | None, limit: int) -> list[LogEntry]:
        statement = select(Member).order_by(Member.created_at.desc()).limit(limit)
        if before is not None:
            statement = statement.where(Member.created_at < before)
        members = (await self._session.execute(statement)).scalars().all()
        return [
            LogEntry(
                id=f"sign_in:{member.id}",
                at=member.created_at,
                kind="sign_in",
                actor=None,
                summary=f"{member.display_name} signed in for the first time",
                detail=None,
                member_id=member.id,
                event_id=None,
                case_number=None,
            )
            for member in members
        ]

    async def _battlenet_log(self, *, before: datetime | None, limit: int) -> list[LogEntry]:
        statement = (
            select(Member).where(Member.battlenet_linked_at.is_not(None)).order_by(Member.battlenet_linked_at.desc())
        ).limit(limit)
        if before is not None:
            statement = statement.where(Member.battlenet_linked_at < before)
        members = (await self._session.execute(statement)).scalars().all()
        entries = []
        for member in members:
            linked_at = member.battlenet_linked_at
            assert linked_at is not None  # noqa: S101 - filtered by the WHERE clause above
            entries.append(
                LogEntry(
                    id=f"battlenet:{member.id}",
                    at=linked_at,
                    kind="battlenet",
                    actor=None,
                    summary=f"{member.display_name} linked Battle.net",
                    detail=None,
                    member_id=member.id,
                    event_id=None,
                    case_number=None,
                )
            )
        return entries

    async def _officer_log(self, *, before: datetime | None, limit: int) -> list[LogEntry]:
        statement = select(OfficerAudit).order_by(OfficerAudit.created_at.desc()).limit(limit)
        if before is not None:
            statement = statement.where(OfficerAudit.created_at < before)
        audits = (await self._session.execute(statement)).scalars().all()
        actor_ids = [audit.actor_member_id for audit in audits if audit.actor_member_id is not None]
        actors = await self._members_by_id(actor_ids)
        entries = []
        for audit in audits:
            actor_member = actors.get(audit.actor_member_id) if audit.actor_member_id is not None else None
            actor = (
                LogActor(
                    display_name=actor_member.display_name,
                    avatar_url=avatar_url(actor_member.discord_id, actor_member.avatar_hash),
                )
                if actor_member is not None
                else None
            )
            member_id, event_id, case_number = _officer_subject_refs(audit)
            entries.append(
                LogEntry(
                    id=f"officer:{audit.id}",
                    at=audit.created_at,
                    kind="officer",
                    actor=actor,
                    summary=audit.summary,
                    detail=None,
                    member_id=member_id,
                    event_id=event_id,
                    case_number=case_number,
                )
            )
        return entries

    async def _moderation_log(self, *, before: datetime | None, limit: int) -> list[LogEntry]:
        statement = (
            select(ModCase)
            .where(ModCase.guild_id == self._web_settings.GUILD_ID)
            .order_by(ModCase.created_at.desc())
            .limit(limit)
        )
        if before is not None:
            statement = statement.where(ModCase.created_at < before)
        cases = (await self._session.execute(statement)).scalars().all()
        discord_ids = list({case.user_id for case in cases} | {case.moderator_id for case in cases})
        members = await self._members_by_discord(discord_ids)
        entries = []
        for case in cases:
            verb = _CASE_ACTION_VERBS.get(case.action, case.action)
            moderator_label = (
                members[case.moderator_id].display_name
                if case.moderator_id in members
                else (f"Moderator {case.moderator_id}")
            )
            user_label = members[case.user_id].display_name if case.user_id in members else f"user {case.user_id}"
            user_member = members.get(case.user_id)
            entries.append(
                LogEntry(
                    id=f"moderation:{case.id}",
                    at=case.created_at,
                    kind="moderation",
                    actor=None,
                    summary=f"{moderator_label} {verb} {user_label}",
                    detail=case.reason,
                    member_id=user_member.id if user_member is not None else None,
                    event_id=None,
                    case_number=case.case_number,
                )
            )
        return entries
