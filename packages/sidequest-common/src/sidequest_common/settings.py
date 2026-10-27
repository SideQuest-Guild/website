"""Environment-driven settings shared by the API and the bot.

Each concern has its own env prefix: ``DB_``, ``API_``, ``DISCORD_``.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_CONFIG = {"env_file": ".env", "extra": "ignore", "case_sensitive": False}


class DatabaseSettings(BaseSettings):
    """Database connection settings (``DB_*``)."""

    model_config = SettingsConfigDict(env_prefix="DB_", **_BASE_CONFIG)

    URL: str = "postgresql+asyncpg://sidequest:sidequest@localhost:5432/sidequest"
    ECHO: bool = False
    POOL_DISABLE: bool = False


class APISettings(BaseSettings):
    """API settings (``API_*``).

    ``KEY`` is the shared secret the bot sends as ``X-API-Key``; both services must agree on it.
    ``URL`` is where the bot reaches the API.
    """

    model_config = SettingsConfigDict(env_prefix="API_", **_BASE_CONFIG)

    KEY: SecretStr
    URL: str = "http://localhost:8000"
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEBUG: bool = False


class DiscordSettings(BaseSettings):
    """Discord bot settings (``DISCORD_*``).

    ``GUILD_ID`` is optional; when set, slash commands sync to that guild instantly instead of globally.
    """

    model_config = SettingsConfigDict(env_prefix="DISCORD_", **_BASE_CONFIG)

    TOKEN: SecretStr
    GUILD_ID: int | None = None
