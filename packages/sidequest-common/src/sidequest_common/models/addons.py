"""WoW addons the guild recommends. Files are hosted elsewhere; we only store links."""

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column


class Addon(UUIDAuditBase):
    """One recommended addon."""

    __tablename__ = "addon"
    __table_args__ = {"comment": "Recommended addons; download/homepage links point to GitHub/CurseForge/Wago."}

    slug: Mapped[str] = mapped_column(Text, unique=True, index=True)
    name: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    download_url: Mapped[str] = mapped_column(Text)
    homepage_url: Mapped[str | None] = mapped_column(Text, default=None)
