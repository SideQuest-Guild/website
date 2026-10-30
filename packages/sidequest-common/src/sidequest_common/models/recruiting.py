"""What roles and classes the guild is recruiting for, as set by officers."""

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import JsonB
from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column


class RecruitingNeeds(UUIDAuditBase):
    """One row per guild: the roles and classes officers have marked as wanted right now."""

    __tablename__ = "recruiting_needs"
    __table_args__ = {"comment": "What roles and classes the guild is recruiting for, set by officers."}

    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)

    roles: Mapped[list[dict]] = mapped_column(JsonB, default=list)
    classes: Mapped[list[dict]] = mapped_column(JsonB, default=list)
