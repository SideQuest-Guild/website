"""Self-assignable role menus (button panels)."""

from uuid import UUID  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship


class RoleMenu(UUIDAuditBase):
    """A message with one button per self-assignable role."""

    __tablename__ = "role_menu"
    __table_args__ = {"comment": "Button role menus posted by the bot."}

    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, default=None)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    max_roles: Mapped[int] = mapped_column(Integer, default=0)
    """Max roles a member may hold from this menu at once; 0 = unlimited."""

    options: Mapped[list[RoleMenuOption]] = relationship(
        back_populates="menu",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RoleMenuOption.position",
    )


class RoleMenuOption(UUIDAuditBase):
    """One role button on a menu."""

    __tablename__ = "role_menu_option"
    __table_args__ = (
        UniqueConstraint("role_menu_id", "role_id"),
        {"comment": "Roles offered by a role menu."},
    )

    role_menu_id: Mapped[UUID] = mapped_column(ForeignKey("role_menu.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int] = mapped_column(BigInteger)
    label: Mapped[str] = mapped_column(String(80))
    emoji: Mapped[str | None] = mapped_column(String(64), default=None)
    description: Mapped[str | None] = mapped_column(String(100), default=None)
    position: Mapped[int] = mapped_column(Integer, default=0)

    menu: Mapped[RoleMenu] = relationship(back_populates="options", lazy="noload")
