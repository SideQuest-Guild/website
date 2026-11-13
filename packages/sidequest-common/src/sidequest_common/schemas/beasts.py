"""Tameable beast reference schemas: read-only Battle.net game data for the Tameable beasts page."""

from pydantic import BaseModel


class BeastSchema(BaseModel):
    """One tameable beast, as returned by `GET /api/beasts` and `GET /api/beasts/{id}`."""

    id: int
    name: str
    family_id: int | None = None
    family: str | None = None
    image_url: str | None = None
    display_id: int | None = None


class BeastFamilySchema(BaseModel):
    """One beast family and how many tameable beasts belong to it, as listed by `GET /api/beasts/families`."""

    id: int
    name: str
    count: int
