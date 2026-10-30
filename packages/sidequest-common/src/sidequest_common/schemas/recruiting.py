"""What roles and classes the guild is recruiting for: public read, officer-managed.

``wow_class``/``class`` follows the same split as ``Signup`` in ``events.py``: ``class`` is a Python keyword, so the
Python-side attribute is ``wow_class``, aliased to the wire name ``class``.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sidequest_common.schemas.events import SignupRole, WowClass

MAX_RECRUITING_NOTE = 140


class RecruitingPriority(StrEnum):
    """How urgently the guild wants this role or class filled."""

    NORMAL = "normal"
    HIGH = "high"


class RecruitingRoleWant(BaseModel):
    """One role the guild is recruiting for."""

    role: SignupRole
    priority: RecruitingPriority = RecruitingPriority.NORMAL
    note: str | None = Field(default=None, max_length=MAX_RECRUITING_NOTE)


class RecruitingClassWant(BaseModel):
    """One class the guild is recruiting for."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    wow_class: WowClass = Field(alias="class")
    priority: RecruitingPriority = RecruitingPriority.NORMAL
    note: str | None = Field(default=None, max_length=MAX_RECRUITING_NOTE)


class Recruiting(BaseModel):
    """``GET /api/recruiting`` (public): the current recruiting needs, empty lists if nothing is wanted."""

    roles: list[RecruitingRoleWant]
    classes: list[RecruitingClassWant]
    updated_at: datetime | None = Field(description="When an officer last saved this. None if it has never been set.")


class RecruitingUpdate(BaseModel):
    """``PUT /api/recruiting`` (officer): replaces the full set. Each role/class may appear at most once."""

    roles: list[RecruitingRoleWant] = Field(default_factory=list)
    classes: list[RecruitingClassWant] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicates(self) -> RecruitingUpdate:
        role_values = [want.role for want in self.roles]
        if len(role_values) != len(set(role_values)):
            msg = "Each role may only be listed once"
            raise ValueError(msg)
        class_values = [want.wow_class for want in self.classes]
        if len(class_values) != len(set(class_values)):
            msg = "Each class may only be listed once"
            raise ValueError(msg)
        return self
