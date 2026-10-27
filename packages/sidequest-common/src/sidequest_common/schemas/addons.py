"""Addon schemas. Files are hosted elsewhere (GitHub releases, CurseForge, Wago); we only store links."""

import re
from datetime import datetime  # pydantic needs it at runtime
from uuid import UUID  # pydantic needs it at runtime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_https_url(value: str | None) -> str | None:
    if value is not None and not value.startswith("https://"):
        msg = "must be an https:// URL"
        raise ValueError(msg)
    return value


class AddonSchema(BaseModel):
    """An addon as returned by ``GET /api/addons``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    summary: str
    version: str
    download_url: str
    homepage_url: str | None
    updated_at: datetime


class AddonCreate(BaseModel):
    """Body for ``POST /api/addons`` (officer)."""

    slug: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    version: str = Field(min_length=1, max_length=50)
    download_url: str = Field(max_length=2000)
    homepage_url: str | None = Field(default=None, max_length=2000)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        if not _SLUG_RE.fullmatch(value):
            msg = "slug must be lowercase a-z0-9- (no leading/trailing/double hyphens)"
            raise ValueError(msg)
        return value

    @field_validator("download_url")
    @classmethod
    def _validate_download_url(cls, value: str) -> str:
        return _validate_https_url(value) or value

    @field_validator("homepage_url")
    @classmethod
    def _validate_homepage_url(cls, value: str | None) -> str | None:
        return _validate_https_url(value)


class AddonUpdate(BaseModel):
    """Body for ``PATCH /api/addons/{id}`` (officer). Only present fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, min_length=1, max_length=2000)
    version: str | None = Field(default=None, min_length=1, max_length=50)
    download_url: str | None = Field(default=None, max_length=2000)
    homepage_url: str | None = Field(default=None, max_length=2000)

    @field_validator("download_url")
    @classmethod
    def _validate_download_url(cls, value: str | None) -> str | None:
        return _validate_https_url(value)

    @field_validator("homepage_url")
    @classmethod
    def _validate_homepage_url(cls, value: str | None) -> str | None:
        return _validate_https_url(value)
