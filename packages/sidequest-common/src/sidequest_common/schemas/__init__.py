"""Pydantic request/response schemas shared by the API and the bot's API client."""

from sidequest_common.schemas.addons import AddonCreate, AddonSchema, AddonUpdate
from sidequest_common.schemas.guild import GuildConfigSchema, GuildConfigUpdate
from sidequest_common.schemas.levels import (
    LeaderboardEntry,
    LeaderboardPage,
    LevelRoleSchema,
    LevelRoleUpsert,
    MemberLevelSchema,
    RankSchema,
    SetXPRequest,
    XPAwardResult,
)
from sidequest_common.schemas.members import Me, MemberListing
from sidequest_common.schemas.moderation import CaseAction, ModCaseCreate, ModCaseSchema, ModCaseUpdate
from sidequest_common.schemas.raids import (
    RaidChartUpdate,
    RaidCounts,
    RaidCreate,
    RaidDetail,
    RaidStatus,
    RaidSummary,
    RaidUpdate,
    Signup,
    SignupMember,
    SignupRole,
    SignupStatus,
    SignupUpsert,
    WowClass,
)
from sidequest_common.schemas.role_menus import (
    RoleMenuCreate,
    RoleMenuOptionSchema,
    RoleMenuOptionUpsert,
    RoleMenuSchema,
    RoleMenuUpdate,
)

__all__ = (
    "AddonCreate",
    "AddonSchema",
    "AddonUpdate",
    "CaseAction",
    "GuildConfigSchema",
    "GuildConfigUpdate",
    "LeaderboardEntry",
    "LeaderboardPage",
    "LevelRoleSchema",
    "LevelRoleUpsert",
    "Me",
    "MemberLevelSchema",
    "MemberListing",
    "ModCaseCreate",
    "ModCaseSchema",
    "ModCaseUpdate",
    "RaidChartUpdate",
    "RaidCounts",
    "RaidCreate",
    "RaidDetail",
    "RaidStatus",
    "RaidSummary",
    "RaidUpdate",
    "RankSchema",
    "RoleMenuCreate",
    "RoleMenuOptionSchema",
    "RoleMenuOptionUpsert",
    "RoleMenuSchema",
    "RoleMenuUpdate",
    "SetXPRequest",
    "Signup",
    "SignupMember",
    "SignupRole",
    "SignupStatus",
    "SignupUpsert",
    "WowClass",
    "XPAwardResult",
)
