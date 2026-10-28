"""ORM models. Importing this package registers every table on ``UUIDAuditBase.metadata``."""

from sidequest_common.models.addons import Addon
from sidequest_common.models.discord_live import DiscordLiveStatus
from sidequest_common.models.events import DiscordEventTombstone, EventSeries, EventSignup, GuildEvent
from sidequest_common.models.guild import GuildConfig
from sidequest_common.models.levels import LevelRole, MemberLevel
from sidequest_common.models.members import Member
from sidequest_common.models.moderation import ModCase
from sidequest_common.models.role_menus import RoleMenu, RoleMenuOption

__all__ = (
    "Addon",
    "DiscordEventTombstone",
    "DiscordLiveStatus",
    "EventSeries",
    "EventSignup",
    "GuildConfig",
    "GuildEvent",
    "LevelRole",
    "Member",
    "MemberLevel",
    "ModCase",
    "RoleMenu",
    "RoleMenuOption",
)
