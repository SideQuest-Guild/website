"""MCP tool definitions: read, officer-write, and GM-only tools registered on the MCP server.

Every tool reads its request context with ``get_context()`` (set by the ASGI handler in ``server.py`` after
authenticating the bearer token). Tools that change data write an audit row via ``record_officer_audit`` so the
action shows on ``/officers/#log``, and prefer existing domain services (events, announcements) so other systems
that depend on them (Discord event sync, forum threads, the weekly board) keep working.
"""

from __future__ import annotations

import functools
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select

from sidequest_api.domain.attendance.services import AttendanceService
from sidequest_api.domain.away.services import AwayService, today_chicago
from sidequest_api.domain.events.services import EventsService
from sidequest_api.domain.guild_hub.services import GuildHubService
from sidequest_api.domain.heroes.services import HeroesService
from sidequest_api.domain.mcp.auth import require_gm
from sidequest_api.domain.mcp.context import get_context, require_bot_token
from sidequest_api.domain.members.services import MembersService
from sidequest_api.lib import discord as discord_lib
from sidequest_api.lib.discord import avatar_url
from sidequest_api.lib.mcp_role_guard import bot_top_role_position, grant_block_reason
from sidequest_api.lib.officer_audit import record_officer_audit
from sidequest_common.models import GuildRole, Member, MemberAwayRange
from sidequest_common.schemas import (
    AttendanceRange,
    EventCreate,
    EventKind,
    EventStatus,
    EventUpdate,
    GuildAnnouncementCreate,
)

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

MAX_MESSAGE_LIMIT = 50
MAX_AUDIT_LIMIT = 50
AUDIT_SUMMARY_MAX = 300


async def _role_names(ctx: Any, role_ids: list[int]) -> dict[int, str]:
    rows = (
        (
            await ctx.session.execute(
                select(GuildRole).where(GuildRole.guild_id == ctx.guild_id, GuildRole.role_id.in_(role_ids))
            )
        )
        .scalars()
        .all()
    )
    return {row.role_id: row.name for row in rows}


# --- Read tools --------------------------------------------------------------------------------------------------


async def whoami() -> dict[str, Any]:
    """The officer this MCP token belongs to: their site member id, Discord id, display name, and roles."""
    ctx = get_context()
    actor = ctx.actor
    role_names = await _role_names(ctx, actor.roles)
    return {
        "member_id": actor.id,
        "discord_id": str(actor.discord_id),
        "display_name": actor.display_name,
        "is_gm": set(ctx.web_settings.GM_ROLE_IDS) & set(actor.roles) != set(),
        "roles": [role_names.get(role_id, str(role_id)) for role_id in actor.roles],
    }


async def find_member(query: str) -> list[dict[str, Any]]:
    """Find guild members by Discord username, display name, or BattleTag (case-insensitive substring match).

    Returns each match's site + Discord view: roles, BattleTag, roster confirmation, Renown, attendance, and away
    dates. Capped at 10 matches.
    """
    ctx = get_context()
    needle = f"%{query.strip()}%"
    statement = (
        select(Member)
        .where(
            Member.username.ilike(needle)
            | Member.global_name.ilike(needle)
            | Member.guild_nick.ilike(needle)
            | Member.battletag.ilike(needle)
        )
        .limit(10)
    )
    members = (await ctx.session.execute(statement)).scalars().all()
    heroes = HeroesService(ctx.session, ctx.web_settings)
    away_service = AwayService(ctx.session)
    results = []
    for member in members:
        role_names = await _role_names(ctx, member.roles)
        profile = await heroes.get_profile(member.id)
        away_ranges = await away_service.list_for_member(member)
        results.append(
            {
                "member_id": member.id,
                "discord_id": str(member.discord_id),
                "display_name": member.display_name,
                "username": member.username,
                "avatar_url": avatar_url(member.discord_id, member.avatar_hash),
                "roles": [role_names.get(role_id, str(role_id)) for role_id in member.roles],
                "battletag": member.battletag,
                "is_guild_member": member.is_guild_member,
                "roster_confirmed_at": member.roster_confirmed_at.isoformat() if member.roster_confirmed_at else None,
                "raid_status": member.raid_status,
                "renown": profile.all_time.ep,
                "raids_attended": profile.all_time.raids_attended,
                "events_attended": profile.all_time.events_attended,
                "attendance_rate": profile.all_time.attendance_rate,
                "away_ranges": [
                    {"start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat(), "note": r.note}
                    for r in away_ranges
                ],
            }
        )
    return results


async def list_events(when: str = "upcoming", kind: str | None = None) -> list[dict[str, Any]]:
    """Guild events. ``when`` is ``"upcoming"`` (default) or ``"past"``; ``kind`` optionally filters one event kind."""
    ctx = get_context()
    events_service = EventsService(ctx.session)
    summaries = await events_service.list_summaries(
        "past" if when == "past" else "upcoming", EventKind(kind) if kind else None, full_access=True
    )
    return [s.model_dump(mode="json") for s in summaries]


async def get_event(event_id: str) -> dict[str, Any]:
    """One event's full detail, including its sign-up roster."""
    ctx = get_context()
    events_service = EventsService(ctx.session)
    detail = await events_service.get_detail(UUID(event_id), viewer=None, full_access=True)
    return detail.model_dump(mode="json")


async def away_this_week() -> list[dict[str, Any]]:
    """Members whose away range overlaps the next 7 days (America/Chicago)."""
    ctx = get_context()
    today = today_chicago()
    end = today + timedelta(days=7)
    statement = (
        select(Member, MemberAwayRange)
        .join(MemberAwayRange, MemberAwayRange.member_id == Member.id)
        .where(MemberAwayRange.start_date <= end, MemberAwayRange.end_date >= today)
        .order_by(MemberAwayRange.start_date)
    )
    rows = (await ctx.session.execute(statement)).all()
    return [
        {
            "member_id": member.id,
            "display_name": member.display_name,
            "start_date": away.start_date.isoformat(),
            "end_date": away.end_date.isoformat(),
            "note": away.note,
        }
        for member, away in rows
    ]


async def list_channels() -> list[dict[str, Any]]:
    """The site guild's Discord channels and categories."""
    ctx = get_context()
    token = require_bot_token(ctx)
    channels = await discord_lib.bot_list_guild_channels(ctx.discord_client, token, ctx.guild_id)
    return [
        {"id": c["id"], "name": c.get("name"), "type": c.get("type"), "parent_id": c.get("parent_id")} for c in channels
    ]


async def list_roles() -> list[dict[str, Any]]:
    """The site guild's Discord roles, with position and whether SideQuest's MCP tools may grant/remove them."""
    ctx = get_context()
    token = require_bot_token(ctx)
    roles = await discord_lib.bot_list_guild_roles(ctx.discord_client, token, ctx.guild_id)
    bot_member = await discord_lib.bot_get_guild_member(ctx.discord_client, token, ctx.guild_id, "@me")
    top_position = bot_top_role_position(roles, bot_member.get("roles", []))
    return [
        {
            "id": role["id"],
            "name": role["name"],
            "position": role["position"],
            "managed": role.get("managed", False),
            "grantable": grant_block_reason(role, guild_id=str(ctx.guild_id), bot_top_position=top_position) is None,
        }
        for role in roles
    ]


async def read_messages(channel_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Recent messages in a Discord channel, newest first, capped at 50."""
    ctx = get_context()
    token = require_bot_token(ctx)
    messages = await discord_lib.bot_get_channel_messages(
        ctx.discord_client, token, int(channel_id), limit=min(max(limit, 1), MAX_MESSAGE_LIMIT)
    )
    return [
        {
            "id": m["id"],
            "author": m.get("author", {}).get("username"),
            "bot_authored": m.get("author", {}).get("bot", False),
            "content": m.get("content"),
            "created_at": m.get("timestamp"),
        }
        for m in messages
    ]


async def discord_audit_log(limit: int = 20) -> list[dict[str, Any]]:
    """Recent Discord server audit log entries, capped at 50."""
    ctx = get_context()
    token = require_bot_token(ctx)
    entries = await discord_lib.bot_get_guild_audit_log(
        ctx.discord_client, token, ctx.guild_id, limit=min(max(limit, 1), MAX_AUDIT_LIMIT)
    )
    return [
        {"id": e.get("id"), "action_type": e.get("action_type"), "user_id": e.get("user_id"), "reason": e.get("reason")}
        for e in entries
    ]


# --- Write tools (officer) ----------------------------------------------------------------------------------------


async def create_event(
    kind: str,
    title: str,
    starts_at: str,
    *,
    location: str = "",
    ends_at: str | None = None,
    size: int | None = None,
    ep_override: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Schedule a new guild event. ``starts_at``/``ends_at`` are ISO 8601 datetimes."""
    ctx = get_context()
    events_service = EventsService(ctx.session)
    data = EventCreate(
        kind=EventKind(kind),
        title=title,
        location=location,
        starts_at=datetime.fromisoformat(starts_at),
        ends_at=datetime.fromisoformat(ends_at) if ends_at else None,
        size=size,
        ep_override=ep_override,
        notes=notes,
    )
    event = await events_service.create_event(data)
    await record_officer_audit(
        ctx.session,
        actor=ctx.actor,
        action="mcp.create_event",
        subject_type="event",
        subject_id=str(event.id),
        summary=f'Created {event.kind} "{event.title}" for {event.starts_at:%b %-d} via MCP',
    )
    detail = await events_service.get_detail(event.id, viewer=None, full_access=True)
    return detail.model_dump(mode="json")


async def update_event(
    event_id: str,
    *,
    kind: str | None = None,
    title: str | None = None,
    location: str | None = None,
    starts_at: str | None = None,
    ends_at: str | None = None,
    size: int | None = None,
    ep_override: int | None = None,
    notes: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Edit a guild event; only the fields given are changed."""
    ctx = get_context()
    events_service = EventsService(ctx.session)
    data = EventUpdate(
        kind=EventKind(kind) if kind else None,
        title=title,
        location=location,
        starts_at=datetime.fromisoformat(starts_at) if starts_at else None,
        ends_at=datetime.fromisoformat(ends_at) if ends_at else None,
        size=size,
        ep_override=ep_override,
        notes=notes,
        status=EventStatus(status) if status else None,
    )
    event = await events_service.update_event(UUID(event_id), data)
    await record_officer_audit(
        ctx.session,
        actor=ctx.actor,
        action="mcp.update_event",
        subject_type="event",
        subject_id=str(event.id),
        summary=f'Updated event "{event.title}" via MCP',
    )
    detail = await events_service.get_detail(event.id, viewer=None, full_access=True)
    return detail.model_dump(mode="json")


async def cancel_event(event_id: str) -> dict[str, Any]:
    """Cancel a guild event (sets its status to cancelled)."""
    ctx = get_context()
    events_service = EventsService(ctx.session)
    event = await events_service.update_event(UUID(event_id), EventUpdate(status=EventStatus.CANCELLED))
    await record_officer_audit(
        ctx.session,
        actor=ctx.actor,
        action="mcp.cancel_event",
        subject_type="event",
        subject_id=str(event.id),
        summary=f'Cancelled event "{event.title}" via MCP',
    )
    detail = await events_service.get_detail(event.id, viewer=None, full_access=True)
    return detail.model_dump(mode="json")


async def post_message(
    channel_id: str, content: str | None = None, embed_title: str | None = None, embed_description: str | None = None
) -> dict[str, Any]:
    """Post a message to a Discord channel, as the bot. ``@everyone``/``@here``/role mentions never ping."""
    ctx = get_context()
    token = require_bot_token(ctx)
    embed = None
    if embed_title or embed_description:
        embed = {k: v for k, v in {"title": embed_title, "description": embed_description}.items() if v}
    message = await discord_lib.bot_send_channel_message(
        ctx.discord_client, token, int(channel_id), content=content, embed=embed
    )
    await record_officer_audit(
        ctx.session,
        actor=ctx.actor,
        action="mcp.post_message",
        subject_type="discord_message",
        subject_id=message["id"],
        summary=f"Posted a message to <#{channel_id}> via MCP"[:AUDIT_SUMMARY_MAX],
    )
    return {"id": message["id"], "channel_id": channel_id}


async def edit_bot_message(channel_id: str, message_id: str, content: str) -> dict[str, Any]:
    """Edit a message the bot authored. Fails if the message wasn't posted by the bot."""
    ctx = get_context()
    token = require_bot_token(ctx)
    message = await discord_lib.bot_edit_channel_message(
        ctx.discord_client, token, int(channel_id), int(message_id), content=content
    )
    await record_officer_audit(
        ctx.session,
        actor=ctx.actor,
        action="mcp.edit_bot_message",
        subject_type="discord_message",
        subject_id=message_id,
        summary=f"Edited a bot message in <#{channel_id}> via MCP"[:AUDIT_SUMMARY_MAX],
    )
    return {"id": message["id"], "channel_id": channel_id}


async def _change_member_role(member_discord_id: str, role_id: str, *, grant: bool) -> dict[str, Any]:
    ctx = get_context()
    token = require_bot_token(ctx)
    roles = await discord_lib.bot_list_guild_roles(ctx.discord_client, token, ctx.guild_id)
    role = next((r for r in roles if r["id"] == role_id), None)
    if role is None:
        msg = f"No role {role_id} on this server"
        raise ToolError(msg)
    bot_member = await discord_lib.bot_get_guild_member(ctx.discord_client, token, ctx.guild_id, "@me")
    top_position = bot_top_role_position(roles, bot_member.get("roles", []))
    block_reason = grant_block_reason(role, guild_id=str(ctx.guild_id), bot_top_position=top_position)
    if block_reason is not None:
        raise ToolError(block_reason)
    if grant:
        await discord_lib.bot_add_guild_member_role(
            ctx.discord_client, token, ctx.guild_id, int(member_discord_id), int(role_id)
        )
    else:
        await discord_lib.bot_remove_guild_member_role(
            ctx.discord_client, token, ctx.guild_id, int(member_discord_id), int(role_id)
        )
    action = "mcp.add_member_role" if grant else "mcp.remove_member_role"
    verb = "Granted" if grant else "Removed"
    await record_officer_audit(
        ctx.session,
        actor=ctx.actor,
        action=action,
        subject_type="member",
        subject_id=member_discord_id,
        summary=f'{verb} role "{role["name"]}" {"to" if grant else "from"} <@{member_discord_id}> via MCP',
    )
    return {"member_discord_id": member_discord_id, "role_id": role_id, "role_name": role["name"]}


async def add_member_role(member_discord_id: str, role_id: str) -> dict[str, Any]:
    """Grant a Discord role to a member. Refuses managed, dangerous, or bot-outranking roles."""
    return await _change_member_role(member_discord_id, role_id, grant=True)


async def remove_member_role(member_discord_id: str, role_id: str) -> dict[str, Any]:
    """Remove a Discord role from a member. Refuses managed, dangerous, or bot-outranking roles."""
    return await _change_member_role(member_discord_id, role_id, grant=False)


async def post_announcement(text: str, *, discord: bool = True) -> dict[str, Any]:
    """Post a guild announcement to the site. If ``discord`` is true (default), the bot also posts it to Discord."""
    ctx = get_context()
    guild_hub = GuildHubService(ctx.session)
    row = await guild_hub.create_announcement(GuildAnnouncementCreate(text=text, discord=discord), ctx.actor)
    await record_officer_audit(
        ctx.session,
        actor=ctx.actor,
        action="mcp.post_announcement",
        subject_type="announcement",
        subject_id=str(row.id),
        summary=f"Posted an announcement via MCP: {text[:200]}",
    )
    return row.model_dump(mode="json")


# --- GM-only tools -------------------------------------------------------------------------------------------------


async def confirm_member_on_roster(member_id: int) -> dict[str, Any]:
    """Mark a member confirmed on the in-game guild roster (GM only)."""
    ctx = get_context()
    require_gm(ctx.actor, ctx.web_settings)
    members_service = MembersService(ctx.session)
    member = await members_service.get_for_officer_action(member_id)
    member = await members_service.confirm_roster(member)
    await record_officer_audit(
        ctx.session,
        actor=ctx.actor,
        action="mcp.confirm_member_on_roster",
        subject_type="member",
        subject_id=str(member.id),
        summary=f"Confirmed {member.display_name} on the roster via MCP",
    )
    confirmed_at = member.roster_confirmed_at
    return {"member_id": member.id, "roster_confirmed_at": confirmed_at.isoformat() if confirmed_at else None}


async def attendance_report(attendance_range: str = "last_30", *, raids_only: bool = False) -> dict[str, Any]:
    """Per-member attendance report (GM only). ``attendance_range`` is ``last_30``, ``season``, or ``all_time``."""
    ctx = get_context()
    require_gm(ctx.actor, ctx.web_settings)
    attendance_service = AttendanceService(ctx.session)
    report = await attendance_service.report(AttendanceRange(attendance_range), raids_only=raids_only)
    return report.model_dump(mode="json")


_READ_TOOLS = (
    whoami,
    find_member,
    list_events,
    get_event,
    away_this_week,
    list_channels,
    list_roles,
    read_messages,
    discord_audit_log,
)
_OFFICER_WRITE_TOOLS = (
    create_event,
    update_event,
    cancel_event,
    post_message,
    edit_bot_message,
    add_member_role,
    remove_member_role,
    post_announcement,
)
_GM_TOOLS = (confirm_member_on_roster, attendance_report)


def _surface_discord_errors(fn: Any) -> Any:
    """Re-raise ``DiscordApiError`` as ``ToolError`` so its message reaches the MCP client, not a generic one."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except discord_lib.DiscordApiError as error:
            raise ToolError(str(error)) from error

    return wrapper


def register_tools(mcp: MCPServer) -> None:
    """Register every MCP tool on ``mcp``."""
    for fn in (*_READ_TOOLS, *_OFFICER_WRITE_TOOLS, *_GM_TOOLS):
        mcp.tool()(_surface_discord_errors(fn))
