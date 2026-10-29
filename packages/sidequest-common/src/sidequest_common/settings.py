"""Environment-driven settings shared by the API and the bot.

Each concern has its own env prefix: ``DB_``, ``API_``, ``DISCORD_``, ``WEB_``.
"""

import json
from typing import Annotated, Any

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_BASE_CONFIG = {"env_file": ".env", "extra": "ignore", "case_sensitive": False}
MIN_SESSION_SECRET_LENGTH = 32


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


class WebSettings(BaseSettings):
    """Member hub / website settings (``WEB_*``).

    Discord OAuth2 login (scopes ``identify guilds.members.read``) for guild members, guild events, and addons.
    ``DISCORD_CLIENT_ID``/``DISCORD_CLIENT_SECRET`` are the OAuth *application* credentials (separate from the
    bot's ``DISCORD_TOKEN``); when either is unset the app still boots, but ``/auth/discord/login`` returns 503.
    ``BATTLENET_CLIENT_ID``/``BATTLENET_CLIENT_SECRET`` (a develop.battle.net API client) let signed-in members link
    their Battle.net account; when unset, linking redirects back to the account page with an explanation.
    """

    model_config = SettingsConfigDict(env_prefix="WEB_", **_BASE_CONFIG)

    BASE_URL: str = "http://localhost:8000"
    SESSION_SECRET: SecretStr | None = None
    DISCORD_CLIENT_ID: str | None = None
    DISCORD_CLIENT_SECRET: SecretStr | None = None
    BATTLENET_CLIENT_ID: str | None = None
    BATTLENET_CLIENT_SECRET: SecretStr | None = None
    GUILD_ID: int = 1564671275316543508
    # Defaults are the SideQuest server's Quest Master (GM) and Quest Guide roles, like GUILD_ID above; the env vars
    # override them. NoDecode: parsed by _parse_role_ids, so both `123,456` and `[123,456]` work in .env.
    OFFICER_ROLE_IDS: Annotated[list[int], NoDecode] = [1564678042381586532, 1564678035117178960]
    GM_ROLE_IDS: Annotated[list[int], NoDecode] = [1564678042381586532]
    COOKIE_SECURE: bool = False

    @property
    def oauth_configured(self) -> bool:
        """Whether both Discord OAuth app credentials are set."""
        return self.DISCORD_CLIENT_ID is not None and self.DISCORD_CLIENT_SECRET is not None

    @property
    def battlenet_configured(self) -> bool:
        """Whether both Battle.net OAuth client credentials are set."""
        return self.BATTLENET_CLIENT_ID is not None and self.BATTLENET_CLIENT_SECRET is not None

    @field_validator("OFFICER_ROLE_IDS", "GM_ROLE_IDS", mode="before")
    @classmethod
    def _parse_role_ids(cls, value: Any) -> Any:
        """Accept a JSON array (``[123,456]``) or a comma-separated list (``123,456``) from the environment."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [part.strip() for part in text.split(",") if part.strip()]

    @model_validator(mode="after")
    def _validate_session_secret_length(self) -> WebSettings:
        if self.SESSION_SECRET is not None and len(self.SESSION_SECRET.get_secret_value()) < MIN_SESSION_SECRET_LENGTH:
            msg = f"WEB_SESSION_SECRET must be at least {MIN_SESSION_SECRET_LENGTH} characters"
            raise ValueError(msg)
        return self
