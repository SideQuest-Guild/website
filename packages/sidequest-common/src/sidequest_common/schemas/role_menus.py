"""Role menu schemas."""

from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field


class RoleMenuOptionSchema(BaseModel):
    """One role button."""

    model_config = ConfigDict(from_attributes=True)

    role_id: int
    label: str
    emoji: str | None
    description: str | None
    position: int


class RoleMenuSchema(BaseModel):
    """A role menu and its options (ordered by ``position``)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    guild_id: int
    channel_id: int
    message_id: int | None
    title: str
    description: str | None
    max_roles: int
    options: list[RoleMenuOptionSchema]


class RoleMenuCreate(BaseModel):
    """Body for ``POST /role-menus``. The bot posts the message afterwards and PATCHes ``message_id``."""

    channel_id: int
    title: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    max_roles: int = Field(default=0, ge=0, le=25)


class RoleMenuUpdate(BaseModel):
    """Partial update for ``PATCH /role-menus/{menu_id}`` (``exclude_unset``)."""

    channel_id: int | None = None
    message_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    max_roles: int | None = Field(default=None, ge=0, le=25)


class RoleMenuOptionUpsert(BaseModel):
    """Body for ``PUT /role-menus/{menu_id}/options/{role_id}``. Discord allows 25 buttons per message."""

    label: str = Field(min_length=1, max_length=80)
    emoji: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=100)
    position: int | None = Field(default=None, ge=0, le=24)
