"""add market report

Revision ID: 38001229e5c2
Revises: d26d80be1863
Create Date: 2026-11-27 23:30:00.000000

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
from sqlalchemy.dialects import postgresql

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
revision = "38001229e5c2"
down_revision = "d26d80be1863"
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
    """schema upgrade migrations go here."""
    op.create_table(
        "market_feed_state",
        sa.Column("id", sa.GUID(length=16), nullable=False),
        sa.Column("house_id", sa.Integer(), nullable=False),
        sa.Column("house_name", sa.Text(), nullable=False),
        sa.Column("snapshot_at", sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("items", sa.Integer(), nullable=False),
        sa.Column("recipes", sa.Integer(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTimeUTC(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_feed_state")),
        comment="The market report feed: one row per auction house, stamped on every feed.",
    )
    with op.batch_alter_table("market_feed_state", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_market_feed_state_house_id"), ["house_id"], unique=True)

    op.create_table(
        "market_item",
        sa.Column("id", sa.GUID(length=16), nullable=False),
        sa.Column("house_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quality", sa.Text(), nullable=True),
        sa.Column("stack_size", sa.Integer(), nullable=False),
        sa.Column("vendor_buy", sa.BigInteger(), nullable=False),
        sa.Column("vendor_sell", sa.BigInteger(), nullable=False),
        sa.Column("min_price", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("market", sa.BigInteger(), nullable=False),
        sa.Column("sale_price", sa.BigInteger(), nullable=False),
        sa.Column("sold_per_day", sa.Float(), nullable=False),
        sa.Column(
            "days",
            sa.JSON()
            .with_variant(postgresql.JSONB(astext_type=sa.Text()), "cockroachdb")
            .with_variant(sa.ORA_JSONB(), "oracle")
            .with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTimeUTC(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_item")),
        sa.UniqueConstraint("house_id", "item_id", name="uq_market_item_house_item"),
        comment="Market report feed: each item's prices and sales at one house; replaced on every feed.",
    )
    with op.batch_alter_table("market_item", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_market_item_house_id"), ["house_id"], unique=False)

    op.create_table(
        "market_recipe",
        sa.Column("id", sa.GUID(length=16), nullable=False),
        sa.Column("house_id", sa.Integer(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("profession", sa.Text(), nullable=False),
        sa.Column("crafted_item_id", sa.Integer(), nullable=False),
        sa.Column("crafted_quantity", sa.Float(), nullable=False),
        sa.Column(
            "reagents",
            sa.JSON()
            .with_variant(postgresql.JSONB(astext_type=sa.Text()), "cockroachdb")
            .with_variant(sa.ORA_JSONB(), "oracle")
            .with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTimeUTC(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_recipe")),
        sa.UniqueConstraint("house_id", "recipe_id", name="uq_market_recipe_house_recipe"),
        comment="Market report feed: recipes and their reagents; replaced on every feed.",
    )
    with op.batch_alter_table("market_recipe", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_market_recipe_house_id"), ["house_id"], unique=False)

    with op.batch_alter_table("guild_config", schema=None) as batch_op:
        batch_op.add_column(sa.Column("market_report_channel_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("market_report_last_day", sa.String(length=10), nullable=True))


def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    with op.batch_alter_table("guild_config", schema=None) as batch_op:
        batch_op.drop_column("market_report_last_day")
        batch_op.drop_column("market_report_channel_id")
    for table in ("market_recipe", "market_item"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(batch_op.f(f"ix_{table}_house_id"))
        op.drop_table(table)
    with op.batch_alter_table("market_feed_state", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_market_feed_state_house_id"))
    op.drop_table("market_feed_state")


def data_upgrades() -> None:
    """Add any optional data upgrade migrations here!"""


def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
