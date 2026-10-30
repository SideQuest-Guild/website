"""Leveling schemas."""

from pydantic import BaseModel, ConfigDict, Field


class XPAwardResult(BaseModel):
    """Outcome of ``POST /members/{user_id}/xp`` (one chat message's worth of XP).

    ``awarded`` is False while the member is on cooldown (or leveling is disabled); every other field then
    reflects the unchanged totals. ``earned_role_ids`` are level-role rewards for every level crossed by this
    award; ``remove_role_ids`` are lower level-roles to take away when the guild has ``level_roles_stack=False``.
    """

    awarded: bool
    amount: int = Field(description="XP (experience points) awarded by this message.")
    xp: int = Field(description="The member's new total XP (experience points).")
    level: int
    previous_level: int
    leveled_up: bool
    earned_role_ids: list[int] = Field(default_factory=list)
    remove_role_ids: list[int] = Field(default_factory=list)


class RankSchema(BaseModel):
    """A member's standing. ``rank`` is 1-based position by XP, or None if they have no XP yet."""

    user_id: int
    rank: int | None
    xp: int = Field(description="The member's total XP (experience points).")
    level: int
    message_count: int
    xp_into_level: int = Field(description="XP (experience points) earned since reaching the current level.")
    xp_for_next_level: int = Field(description="XP (experience points) needed to reach the next level.")


class LeaderboardEntry(BaseModel):
    """One leaderboard row."""

    rank: int
    user_id: int
    xp: int = Field(description="The member's total XP (experience points).")
    level: int
    message_count: int


class LeaderboardPage(BaseModel):
    """A page of the leaderboard, highest XP first."""

    entries: list[LeaderboardEntry]
    total: int
    limit: int
    offset: int


MAX_XP = 10_000_000_000
"""Ceiling for admin XP overrides (~level 1800); keeps the level calculation bounded and fits a BIGINT."""


class SetXPRequest(BaseModel):
    """Admin override of a member's XP total (level is recomputed)."""

    xp: int = Field(ge=0, le=MAX_XP, description="The new total XP (experience points) to set.")


class MemberLevelSchema(BaseModel):
    """Raw stored level row."""

    model_config = ConfigDict(from_attributes=True)

    guild_id: int
    user_id: int
    xp: int = Field(description="The member's total XP (experience points).")
    level: int
    message_count: int


class LevelRoleSchema(BaseModel):
    """Role rewarded at a level."""

    model_config = ConfigDict(from_attributes=True)

    level: int
    role_id: int


class LevelRoleUpsert(BaseModel):
    """Body for ``PUT /level-roles/{level}``."""

    role_id: int
