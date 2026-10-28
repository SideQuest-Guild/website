"""rename raids to guild events

Revision ID: ae7171335e72
Revises: 2c03a1d13942
Create Date: 2026-10-27 21:47:59.024492

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
revision = "ae7171335e72"
down_revision = "2c03a1d13942"
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
    """Rename raid/raid_signup into guild_event/event_signup, keeping data. Raids become kind "raid"."""
    # --- raid -> guild_event ---
    op.rename_table("raid", "guild_event")
    op.execute("ALTER TABLE guild_event RENAME CONSTRAINT pk_raid TO pk_guild_event")
    op.execute("ALTER TABLE guild_event RENAME CONSTRAINT uq_raid_discord_event_id TO uq_guild_event_discord_event_id")
    op.execute("ALTER INDEX ix_raid_starts_at RENAME TO ix_guild_event_starts_at")
    op.alter_column("guild_event", "instance", new_column_name="location")
    op.add_column("guild_event", sa.Column("kind", sa.String(length=20), nullable=False, server_default="raid"))
    op.alter_column("guild_event", "kind", server_default=None)
    op.execute(
        "COMMENT ON TABLE guild_event IS 'Scheduled guild events (raids, dungeons, leveling, pvp, social, other).'"
    )

    # --- raid_signup -> event_signup ---
    op.rename_table("raid_signup", "event_signup")
    op.execute("ALTER TABLE event_signup RENAME CONSTRAINT pk_raid_signup TO pk_event_signup")
    op.execute(
        "ALTER TABLE event_signup RENAME CONSTRAINT fk_raid_signup_raid_id_raid TO fk_event_signup_event_id_guild_event"
    )
    op.execute(
        "ALTER TABLE event_signup RENAME CONSTRAINT fk_raid_signup_member_id_member TO fk_event_signup_member_id_member"
    )
    op.execute("ALTER TABLE event_signup RENAME CONSTRAINT uq_raid_signup_raid_member TO uq_event_signup_event_member")
    op.execute("ALTER INDEX ix_raid_signup_raid_id RENAME TO ix_event_signup_event_id")
    op.execute("ALTER INDEX ix_raid_signup_member_id RENAME TO ix_event_signup_member_id")
    op.alter_column("event_signup", "raid_id", new_column_name="event_id")
    op.alter_column("event_signup", "raid_group", new_column_name="chart_group")
    op.alter_column("event_signup", "character", nullable=True)
    op.alter_column("event_signup", "wow_class", nullable=True)
    op.alter_column("event_signup", "role", nullable=True)
    op.execute(
        "COMMENT ON TABLE event_signup IS "
        "'Member signups for a guild event, including the officer-assigned raid chart (group/bench).'"
    )

    # --- cosmetic: the tombstone comment used to say "raid" ---
    op.execute(
        "COMMENT ON TABLE discord_event_tombstone IS "
        "'Discord scheduled events still to delete after their guild event was deleted.'"
    )


def schema_downgrades() -> None:
    """Reverse the renames; data is preserved (``kind`` is dropped, so non-raid rows lose that distinction)."""
    op.execute(
        "COMMENT ON TABLE discord_event_tombstone IS "
        "'Discord scheduled events still to delete after their raid was deleted.'"
    )

    # --- event_signup -> raid_signup ---
    op.execute(
        "COMMENT ON TABLE event_signup IS "
        "'Member signups for a raid, including the officer-assigned raid chart (group/bench).'"
    )
    op.alter_column("event_signup", "role", nullable=False)
    op.alter_column("event_signup", "wow_class", nullable=False)
    op.alter_column("event_signup", "character", nullable=False)
    op.alter_column("event_signup", "chart_group", new_column_name="raid_group")
    op.alter_column("event_signup", "event_id", new_column_name="raid_id")
    op.execute("ALTER INDEX ix_event_signup_member_id RENAME TO ix_raid_signup_member_id")
    op.execute("ALTER INDEX ix_event_signup_event_id RENAME TO ix_raid_signup_raid_id")
    op.execute("ALTER TABLE event_signup RENAME CONSTRAINT uq_event_signup_event_member TO uq_raid_signup_raid_member")
    op.execute(
        "ALTER TABLE event_signup RENAME CONSTRAINT fk_event_signup_member_id_member TO fk_raid_signup_member_id_member"
    )
    op.execute(
        "ALTER TABLE event_signup RENAME CONSTRAINT fk_event_signup_event_id_guild_event TO fk_raid_signup_raid_id_raid"
    )
    op.execute("ALTER TABLE event_signup RENAME CONSTRAINT pk_event_signup TO pk_raid_signup")
    op.rename_table("event_signup", "raid_signup")

    # --- guild_event -> raid ---
    op.execute("COMMENT ON TABLE guild_event IS 'Scheduled raid events.'")
    op.drop_column("guild_event", "kind")
    op.alter_column("guild_event", "location", new_column_name="instance")
    op.execute("ALTER INDEX ix_guild_event_starts_at RENAME TO ix_raid_starts_at")
    op.execute("ALTER TABLE guild_event RENAME CONSTRAINT uq_guild_event_discord_event_id TO uq_raid_discord_event_id")
    op.execute("ALTER TABLE guild_event RENAME CONSTRAINT pk_guild_event TO pk_raid")
    op.rename_table("guild_event", "raid")


def data_upgrades() -> None:
    """Add any optional data upgrade migrations here!"""


def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
