"""ORM models. Importing this package registers every table on ``UUIDAuditBase.metadata``."""

from sidequest_common.models.activity import MemberActivityHour
from sidequest_common.models.addons import Addon
from sidequest_common.models.auctions import (
    AuctionAlert,
    AuctionDailyHistory,
    AuctionHousePriceRow,
    AuctionHouseState,
    AuctionWatch,
)
from sidequest_common.models.audit import OfficerAudit
from sidequest_common.models.away import MemberAwayRange
from sidequest_common.models.badges import MemberBadge
from sidequest_common.models.characters import BattlenetCharacter, CharacterMilestone
from sidequest_common.models.directory import (
    CharacterDirectoryChar,
    CharacterDirectoryCooldowns,
    CharacterDirectoryMarket,
    CharacterDirectorySection,
    CharacterDirectoryStock,
    ItemName,
)
from sidequest_common.models.discord_live import DiscordLiveStatus
from sidequest_common.models.epgp import (
    Encounter,
    EpgpDeviceAuthorization,
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
from sidequest_common.models.groups import GroupSession, GroupSessionMember, GroupSessionPair, GroupSessionTranscript
from sidequest_common.models.guild import GuildConfig
from sidequest_common.models.guild_hub import (
    CharacterProfession,
    CharacterRecipeLink,
    GuildAnnouncement,
    GuildBankLogEntry,
    GuildNewsEvent,
    GuildRank,
    GuildRecruit,
    GuildRosterSnapshot,
    MemberNote,
    ProfessionRecipe,
    RecruitVote,
)
from sidequest_common.models.guild_roles import GuildRole
from sidequest_common.models.items import BattlenetItem, ItemWish
from sidequest_common.models.levels import LevelRole, MemberLevel, XPGrant
from sidequest_common.models.mcp import McpToken
from sidequest_common.models.members import Member
from sidequest_common.models.moderation import ModCase
from sidequest_common.models.pvp import BattlegroundMatch, BattlegroundScore
from sidequest_common.models.recruiting import RecruitingNeeds
from sidequest_common.models.role_menus import RoleMenu, RoleMenuOption
from sidequest_common.models.role_resets import MemberRoleReset
from sidequest_common.models.talents import TalentBuild

__all__ = (
    "Addon",
    "AuctionAlert",
    "AuctionDailyHistory",
    "AuctionHousePriceRow",
    "AuctionHouseState",
    "AuctionWatch",
    "BattlegroundMatch",
    "BattlegroundScore",
    "BattlenetCharacter",
    "BattlenetItem",
    "CharacterDirectoryChar",
    "CharacterDirectoryCooldowns",
    "CharacterDirectoryMarket",
    "CharacterDirectorySection",
    "CharacterDirectoryStock",
    "CharacterMilestone",
    "CharacterProfession",
    "CharacterRecipeLink",
    "DiscordEventTombstone",
    "DiscordLiveStatus",
    "Encounter",
    "EpgpDeviceAuthorization",
    "EpgpImportAudit",
    "EpgpLedgerEntry",
    "EpgpSyncToken",
    "EventDiscordInterest",
    "EventSeries",
    "EventSignup",
    "EventSignupActivity",
    "EventVoicePresence",
    "GroupSession",
    "GroupSessionMember",
    "GroupSessionPair",
    "GroupSessionTranscript",
    "GuildAnnouncement",
    "GuildBankLogEntry",
    "GuildConfig",
    "GuildEvent",
    "GuildNewsEvent",
    "GuildRank",
    "GuildRecruit",
    "GuildRole",
    "GuildRosterSnapshot",
    "ItemName",
    "ItemWish",
    "LevelRole",
    "LootAward",
    "McpToken",
    "Member",
    "MemberActivityHour",
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
    "TalentBuild",
    "WowCharacter",
    "XPGrant",
)
