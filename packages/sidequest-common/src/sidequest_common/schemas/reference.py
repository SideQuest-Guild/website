"""Quest and achievement reference schemas: read-only Battle.net game data for the Quests and Achievements pages."""

from pydantic import BaseModel, Field

QUEST_SEARCH_MIN_LENGTH = 2
"""The fewest letters `GET /api/quests/search`'s `q` will accept."""
QUEST_SEARCH_LIMIT = 25
"""The most results `GET /api/quests/search` will ever return."""


class QuestAreaSummary(BaseModel):
    """One quest zone, as listed on `GET /api/quests/areas`."""

    id: int
    name: str


class QuestSummary(BaseModel):
    """One quest in a zone, as listed on `GET /api/quests/areas/{id}`."""

    id: int
    title: str


class QuestAreaSchema(BaseModel):
    """A quest zone and the quests that take place there, as returned by `GET /api/quests/areas/{id}`."""

    id: int
    name: str
    quests: list[QuestSummary]


class QuestSearchResult(BaseModel):
    """One match from `GET /api/quests/search`, best matches first."""

    id: int
    title: str
    area: str | None = None


class QuestRewardItem(BaseModel):
    """One item a quest rewards on completion."""

    item_id: int
    name: str


class QuestReputationReward(BaseModel):
    """Reputation a quest grants (or takes away) toward one faction on completion."""

    faction: str
    value: int


class QuestRewardsSchema(BaseModel):
    """What completing a quest gives: experience, money, items, and reputation."""

    experience: int | None = None
    money: int | None = Field(None, description="Copper awarded on completion.")
    items: list[QuestRewardItem] = Field(default_factory=list)
    reputations: list[QuestReputationReward] = Field(default_factory=list)


class QuestRef(BaseModel):
    """A quest's id and title, as referenced from another quest's chain, exclusions or follow-ups."""

    id: int
    title: str


class QuestRequirementRef(QuestRef):
    """A quest required to start another.

    Items sharing a non-`null` `group` are alternatives: completing any one of them satisfies that group. Items
    with `group` `null` must each be completed.
    """

    group: int | None = None


class QuestSchema(BaseModel):
    """A single quest. Description placeholders like `{class}` appear as Battle.net sends them."""

    id: int
    title: str
    description: str | None = None
    area: str | None = None
    category: str | None = None
    type: str | None = None
    min_level: int | None = None
    max_level: int | None = None
    is_repeatable: bool = False
    is_daily: bool = False
    is_weekly: bool = False
    rewards: QuestRewardsSchema
    requires: list[QuestRequirementRef] = Field(
        default_factory=list,
        description="Quests you must have completed first, flattened from Battle.net's condition tree.",
    )
    excludes: list[QuestRef] = Field(
        default_factory=list,
        description="Quests that, once completed, lock this one out (Battle.net's `must_be_incomplete` targets).",
    )
    chain: list[QuestRef] = Field(
        default_factory=list,
        description=(
            "Earlier quests leading up to this one, earliest first; does not include this quest. Found by "
            "following the first required prerequisite back at each step, capped at 25 steps."
        ),
    )
    leads_to: list[QuestRef] = Field(
        default_factory=list,
        description=(
            "Quests whose prerequisites include this one, found by scanning this quest's zone and the zones of "
            "any direct follow-ups found there. A follow-up quest that starts in a different, undiscovered zone "
            "may be missed."
        ),
    )


class AchievementCategorySummary(BaseModel):
    """One achievement category, as listed under a root category on `GET /api/achievements/categories`."""

    id: int
    name: str


class AchievementCategoryTree(BaseModel):
    """One root achievement category and its subcategories, as returned by `GET /api/achievements/categories`."""

    id: int
    name: str
    children: list[AchievementCategorySummary]


class AchievementSummary(BaseModel):
    """One achievement in a category, as listed on `GET /api/achievements/categories/{id}`."""

    id: int
    name: str
    points: int
    icon_url: str | None = None


class AchievementCategorySchema(BaseModel):
    """An achievement category and its achievements, as returned by `GET /api/achievements/categories/{id}`."""

    id: int
    name: str
    achievements: list[AchievementSummary]


class AchievementCriterion(BaseModel):
    """One condition that completes an achievement, or one branch of its criteria tree."""

    description: str | None = None
    amount: int
    children: list["AchievementCriterion"] = Field(default_factory=list)


AchievementCriterion.model_rebuild()


class AchievementSchema(BaseModel):
    """A single achievement, as returned by `GET /api/achievements/{id}`."""

    id: int
    name: str
    description: str
    points: int
    icon_url: str | None = None
    category: str | None = None
    reward_description: str | None = None
    criteria: AchievementCriterion
