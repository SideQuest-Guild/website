"""Quest and achievement reference schemas: read-only Battle.net game data for the Quests and Achievements pages."""

from pydantic import BaseModel, Field


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
