"""ORM models. Importing this package registers every table on ``UUIDAuditBase.metadata``."""

from sidequest_common.models.addons import Addon
from sidequest_common.models.audit import OfficerAudit
from sidequest_common.models.discord_live import DiscordLiveStatus
from sidequest_common.models.events import (
    DiscordEventTombstone,
    EventDiscordInterest,
    EventSeries,
    EventSignup,
    EventSignupActivity,
    GuildEvent,
)
from sidequest_common.models.guild import GuildConfig
from sidequest_common.models.guild_roles import GuildRole
from sidequest_common.models.levels import LevelRole, MemberLevel
from sidequest_common.models.members import Member
from sidequest_common.models.moderation import ModCase
from sidequest_common.models.role_menus import RoleMenu, RoleMenuOption

__all__ = (
    "Addon",
    "DiscordEventTombstone",
    "DiscordLiveStatus",
    "EventDiscordInterest",
    "EventSeries",
    "EventSignup",
    "EventSignupActivity",
    "GuildConfig",
    "GuildEvent",
    "GuildRole",
    "LevelRole",
    "Member",
    "MemberLevel",
    "ModCase",
    "OfficerAudit",
    "RoleMenu",
    "RoleMenuOption",
)
