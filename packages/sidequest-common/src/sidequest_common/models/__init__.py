"""ORM models. Importing this package registers every table on ``UUIDAuditBase.metadata``."""

from sidequest_common.models.addons import Addon
from sidequest_common.models.audit import OfficerAudit
from sidequest_common.models.away import MemberAwayRange
from sidequest_common.models.badges import MemberBadge
from sidequest_common.models.discord_live import DiscordLiveStatus
from sidequest_common.models.epgp import (
    Encounter,
    EpgpImportAudit,
    EpgpLedgerEntry,
    EpgpSyncToken,
    LootAward,
    RaidSession,
    SessionCharacterPresence,
    WowCharacter,
)
from sidequest_common.models.events import (
    DiscordEventTombstone,
    EventDiscordInterest,
    EventSeries,
    EventSignup,
    EventSignupActivity,
    EventVoicePresence,
    GuildEvent,
)
from sidequest_common.models.guild import GuildConfig
from sidequest_common.models.guild_hub import (
    CharacterProfession,
    CharacterRecipeLink,
    GuildAnnouncement,
    GuildBankLogEntry,
    GuildNewsEvent,
    GuildRecruit,
    GuildRosterSnapshot,
    MemberNote,
    ProfessionRecipe,
    RecruitVote,
)
from sidequest_common.models.guild_roles import GuildRole
from sidequest_common.models.levels import LevelRole, MemberLevel
from sidequest_common.models.members import Member
from sidequest_common.models.moderation import ModCase
from sidequest_common.models.recruiting import RecruitingNeeds
from sidequest_common.models.role_menus import RoleMenu, RoleMenuOption
from sidequest_common.models.role_resets import MemberRoleReset

__all__ = (
    "Addon",
    "CharacterProfession",
    "CharacterRecipeLink",
    "DiscordEventTombstone",
    "DiscordLiveStatus",
    "Encounter",
    "EpgpImportAudit",
    "EpgpLedgerEntry",
    "EpgpSyncToken",
    "EventDiscordInterest",
    "EventSeries",
    "EventSignup",
    "EventSignupActivity",
    "EventVoicePresence",
    "GuildAnnouncement",
    "GuildBankLogEntry",
    "GuildConfig",
    "GuildEvent",
    "GuildNewsEvent",
    "GuildRecruit",
    "GuildRole",
    "GuildRosterSnapshot",
    "LevelRole",
    "LootAward",
    "Member",
    "MemberAwayRange",
    "MemberBadge",
    "MemberLevel",
    "MemberNote",
    "MemberRoleReset",
    "ModCase",
    "OfficerAudit",
    "ProfessionRecipe",
    "RaidSession",
    "RecruitVote",
    "RecruitingNeeds",
    "RoleMenu",
    "RoleMenuOption",
    "SessionCharacterPresence",
    "WowCharacter",
)
