"""add attendance EP override to guild events and series

Revision ID: e5c2a9b7d1f4
Revises: b7a3f91ce2d4
Create Date: 2026-10-28 00:00:00.000000

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
revision = "e5c2a9b7d1f4"
down_revision = "b7a3f91ce2d4"
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
    """Attendance EP override columns, and the guild_event comment gains the transmog kind."""
    with op.batch_alter_table("guild_event", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ep_override", sa.Integer(), nullable=True))
    with op.batch_alter_table("event_series", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ep_override", sa.Integer(), nullable=True))
    op.create_table_comment(
        "guild_event",
        "Scheduled guild events (raids, dungeons, leveling, pvp, social, transmog, other).",
        existing_comment="Scheduled guild events (raids, dungeons, leveling, pvp, social, other).",
    )


def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    op.create_table_comment(
        "guild_event",
        "Scheduled guild events (raids, dungeons, leveling, pvp, social, other).",
        existing_comment="Scheduled guild events (raids, dungeons, leveling, pvp, social, transmog, other).",
    )
    with op.batch_alter_table("event_series", schema=None) as batch_op:
        batch_op.drop_column("ep_override")
    with op.batch_alter_table("guild_event", schema=None) as batch_op:
        batch_op.drop_column("ep_override")


def data_upgrades() -> None:
    """Add any optional data upgrade migrations here!"""


def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
