"""Talent calculator schemas: a class's three talent trees from Battle.net, and members' saved builds.

``class`` is a Python keyword, so the Python-side attribute is ``wow_class``; ``Field(alias=...)`` maps it to the
wire name ``class`` in both directions, same as ``sidequest_common.schemas.events``.

A build's ``code`` holds one digit per talent node (its spent rank, 0-9), node order sorted by
``(row, col)`` within each tree, the three trees joined by ``-``; trailing zeros may be trimmed. This is also the
share-link format: ``/talents/?class=druid&build=<code>``.
"""

from datetime import datetime  # pydantic needs it at runtime
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field

from sidequest_common.schemas.events import WowClass

MAX_TALENT_POINTS = 51
FIRST_TALENT_LEVEL = 10
TALENT_ROW_POINTS = 5
"""A tree row opens once this many points, times the row minus one, are spent in that tree."""
MAX_TALENT_BUILDS = 20
TALENT_BUILD_NAME_MAX = 60
TALENT_BUILD_NOTE_MAX = 200


class TalentRank(BaseModel):
    """One learnable rank of a talent node: the spell it grants and that rank's tooltip text."""

    spell_id: int
    description: str


class TalentNode(BaseModel):
    """One node in a specialization's talent tree, positioned on its grid."""

    id: int
    row: int
    col: int
    max_rank: int
    talent_id: int
    name: str
    ranks: list[TalentRank]
    requires: int | None = Field(description="The node id that must be at max rank before this one, or null.")


class TalentTreeSchema(BaseModel):
    """One specialization's talent tree, as shown on the calculator."""

    spec_id: int
    name: str
    icon_url: str | None
    nodes: list[TalentNode]


class ClassTalents(BaseModel):
    """A class's three talent trees, as returned by ``GET /api/talents/{wow_class}``."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    wow_class: WowClass = Field(alias="class")
    trees: list[TalentTreeSchema] = Field(description="The class's three specialization trees, in spec order.")
    max_points: int = Field(default=MAX_TALENT_POINTS, description="The most points a build may spend in total.")
    first_level: int = Field(default=FIRST_TALENT_LEVEL, description="The level a character gets its first point.")


class TalentBuildCreate(BaseModel):
    """Body for ``POST /api/me/talent-builds``: a build the member wants to save."""

    model_config = ConfigDict(populate_by_name=True)

    wow_class: WowClass = Field(alias="class")
    name: str = Field(min_length=1, max_length=TALENT_BUILD_NAME_MAX)
    code: str = Field(min_length=1, max_length=200, description="The build's talent code; see the module docs.")
    note: str | None = Field(default=None, max_length=TALENT_BUILD_NOTE_MAX)


class TalentBuildPinUpdate(BaseModel):
    """Body for ``PUT /api/talent-builds/{id}/pin`` (officer): pin or unpin a build for raids."""

    pinned: bool


class TalentBuildSchema(BaseModel):
    """A saved talent build, as listed by ``GET /api/me/talent-builds`` or ``GET /api/talent-builds``."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, serialize_by_alias=True)

    id: UUID
    wow_class: WowClass = Field(alias="class")
    name: str
    code: str
    note: str | None
    pinned: bool
    member_id: int
    member_name: str
    created_at: datetime
