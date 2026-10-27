"""Pydantic request/response schemas shared by the API and the bot's API client."""

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
from sidequest_common.schemas.moderation import CaseAction, ModCaseCreate, ModCaseSchema, ModCaseUpdate
from sidequest_common.schemas.role_menus import (
    RoleMenuCreate,
    RoleMenuOptionSchema,
    RoleMenuOptionUpsert,
    RoleMenuSchema,
    RoleMenuUpdate,
)

__all__ = (
    "CaseAction",
    "GuildConfigSchema",
    "GuildConfigUpdate",
    "LeaderboardEntry",
    "LeaderboardPage",
    "LevelRoleSchema",
    "LevelRoleUpsert",
    "MemberLevelSchema",
    "ModCaseCreate",
    "ModCaseSchema",
    "ModCaseUpdate",
    "RankSchema",
    "RoleMenuCreate",
    "RoleMenuOptionSchema",
    "RoleMenuOptionUpsert",
    "RoleMenuSchema",
    "RoleMenuUpdate",
    "SetXPRequest",
    "XPAwardResult",
)
