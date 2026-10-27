"""advanced-alchemy wiring, built from settings at app-creation time (no import-time engine)."""

from pathlib import Path
from typing import TYPE_CHECKING

from advanced_alchemy.extensions.litestar import (
    AlembicAsyncConfig,
    AsyncSessionConfig,
    EngineConfig,
    SQLAlchemyAsyncConfig,
    async_autocommit_before_send_handler,
)
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from sidequest_common.settings import DatabaseSettings

MIGRATIONS_PATH = Path(__file__).parent / "migrations"
SESSION_DEPENDENCY_KEY = "db_session"


def build_alchemy_config(settings: DatabaseSettings) -> SQLAlchemyAsyncConfig:
    """SQLAlchemy config for ``settings``. Tables are managed by alembic (``litestar database upgrade``)."""
    import sidequest_common.models  # noqa: F401, PLC0415  # register all tables on the shared metadata

    engine_config = EngineConfig(echo=settings.ECHO)
    if settings.POOL_DISABLE:
        engine_config = EngineConfig(echo=settings.ECHO, poolclass=NullPool)
    return SQLAlchemyAsyncConfig(
        connection_string=settings.URL,
        engine_config=engine_config,
        session_config=AsyncSessionConfig(expire_on_commit=False),
        session_dependency_key=SESSION_DEPENDENCY_KEY,
        before_send_handler=async_autocommit_before_send_handler,
        alembic_config=AlembicAsyncConfig(
            script_location=str(MIGRATIONS_PATH),
            version_table_name="alembic_version",
        ),
    )
