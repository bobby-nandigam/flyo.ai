"""Application configuration, loaded from environment (12-factor)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_name: str = "TravelRefund Intelligence"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)

    # Security
    jwt_secret: str = Field(default="dev-only-change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900          # 15 min
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14  # 14 days

    # Data stores
    database_url: str = Field(
        default="postgresql+psycopg://flyo:flyo@localhost:5432/flyo"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # AI (optional; investigation agent is simulated without a key)
    openai_api_key: str | None = Field(default=None)
    ai_enabled: bool = Field(default=False)

    # Defaults
    default_currency: str = "INR"


@lru_cache
def get_settings() -> Settings:
    return Settings()
