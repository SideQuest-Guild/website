"""add event attendance

Revision ID: b4d0f6a2e5c7
Revises: cfdaf338ac8e
Create Date: 2026-10-29 00:00:00.000000

"""

import warnings
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from advanced_alchemy.types import (
    Bool,
    EncryptedString,
    EncryptedText,
    GUID,
    JsonB,
    ORA_JSONB,
    DateTimeUTC,
    StoredObject,
    PasswordHash,
    FernetBackend,
    TOTPSecret,
    OneTimeCode,
)
from advanced_alchemy.types.encrypted_string import PGCryptoBackend
from advanced_alchemy.types.password_hash.argon2 import Argon2Hasher
from advanced_alchemy.types.password_hash.passlib import PasslibHasher
from advanced_alchemy.types.password_hash.pwdlib import PwdlibHasher
from sqlalchemy import Text  # noqa: F401
from sqlalchemy.dialects import postgresql  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ("downgrade", "upgrade", "schema_upgrades", "schema_downgrades", "data_upgrades", "data_downgrades")

sa.GUID = GUID
sa.Bool = Bool
sa.DateTimeUTC = DateTimeUTC
sa.JsonB = JsonB
sa.ORA_JSONB = ORA_JSONB
sa.EncryptedString = EncryptedString
sa.EncryptedText = EncryptedText
sa.StoredObject = StoredObject
sa.PasswordHash = PasswordHash
sa.Argon2Hasher = Argon2Hasher
sa.PasslibHasher = PasslibHasher
sa.PwdlibHasher = PwdlibHasher
sa.FernetBackend = FernetBackend
sa.PGCryptoBackend = PGCryptoBackend
sa.TOTPSecret = TOTPSecret
sa.OneTimeCode = OneTimeCode

# revision identifiers, used by Alembic.
revision = "b4d0f6a2e5c7"
down_revision = "d9f3a7c2b6e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            schema_upgrades()
            data_upgrades()


def downgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            data_downgrades()
            schema_downgrades()


def schema_upgrades() -> None:
    """Attendance tracking: who was marked present, walk-ins, and bot-reported voice minutes per event."""
    with op.batch_alter_table("guild_event", schema=None) as batch_op:
        batch_op.add_column(sa.Column("attendance_taken_at", sa.DateTimeUTC(timezone=True), nullable=True))
    with op.batch_alter_table("event_signup", schema=None) as batch_op:
        batch_op.add_column(sa.Column("attended", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("is_walk_in", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "event_voice_presence",
        sa.Column("id", sa.GUID(length=16), nullable=False),
        sa.Column("event_id", sa.GUID(length=16), nullable=False),
        sa.Column("discord_id", sa.BigInteger(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["guild_event.id"],
            name=op.f("fk_event_voice_presence_event_id_guild_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_voice_presence")),
        sa.UniqueConstraint("event_id", "discord_id", name="uq_event_voice_presence_event_discord"),
        comment="Minutes a Discord member spent in guild voice channels during an event, bot-reported.",
    )
    with op.batch_alter_table("event_voice_presence", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_event_voice_presence_event_id"), ["event_id"], unique=False)


def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    with op.batch_alter_table("event_voice_presence", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_event_voice_presence_event_id"))
    op.drop_table("event_voice_presence")
    with op.batch_alter_table("event_signup", schema=None) as batch_op:
        batch_op.drop_column("is_walk_in")
        batch_op.drop_column("attended")
    with op.batch_alter_table("guild_event", schema=None) as batch_op:
        batch_op.drop_column("attendance_taken_at")


def data_upgrades() -> None:
    """Add any optional data upgrade migrations here!"""


def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
