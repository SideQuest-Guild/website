"""Professions, recipes, and class/spec art.

Read-only Battle.net game data for the Recipes pages and the small class/spec icons drawn across the site
(characters, heroes, raid sign-ups).
"""

from pydantic import BaseModel, ConfigDict, Field

from sidequest_common.schemas.events import WowClass


class ProfessionSummary(BaseModel):
    """One profession, as listed on `GET /api/professions`."""

    id: int
    name: str
    type: str = Field(description="`PRIMARY` or `SECONDARY`, as Battle.net names it.")
    icon_url: str | None
    skill_tier_id: int


class RecipeRefSchema(BaseModel):
    """A recipe reference in a skill tier category: just enough to list and link it."""

    id: int
    name: str


class RecipeCategorySchema(BaseModel):
    """A group of recipes in a profession's skill tier, such as Weapon Stones."""

    name: str
    recipes: list[RecipeRefSchema]


class ProfessionSkillTierSchema(BaseModel):
    """A profession's skill tier, as returned by `GET /api/professions/{id}`."""

    profession_id: int
    profession_name: str
    categories: list[RecipeCategorySchema]


class RecipeCraftedItem(BaseModel):
    """The item a recipe makes."""

    item_id: int
    name: str
    quality: str | None = None


class RecipeReagent(BaseModel):
    """One reagent a recipe uses, and how many."""

    item_id: int
    name: str
    quantity: int
    quality: str | None = None


class RecipeCrafter(BaseModel):
    """A guild character that knows a recipe, matched from the addon's profession data by profession and name."""

    character: str
    member_id: int | None
    member_name: str | None
    skill: int


class RecipeDetail(BaseModel):
    """A single recipe, as returned by `GET /api/recipes/{id}`."""

    recipe_id: int
    name: str
    description: str | None
    rank: int | None
    profession: str | None = Field(description="The profession this recipe belongs to, if the catalog has it.")
    icon_url: str | None
    crafted_item: RecipeCraftedItem | None
    crafted_quantity: str | None = Field(description='How many the recipe makes, as plain text, e.g. "Makes 2-4".')
    reagents: list[RecipeReagent]
    crafters: list[RecipeCrafter]


class GameSpecSchema(BaseModel):
    """One class specialization, for the site's small spec icons."""

    id: int
    name: str
    icon_url: str | None


class GameClassSchema(BaseModel):
    """One playable class and its specializations, for the site's small class/spec icons."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    wow_class: WowClass = Field(alias="class", serialization_alias="class")
    name: str
    icon_url: str | None
    specs: list[GameSpecSchema]
