from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Status(StrEnum):
    """The only states used by the document-processing lifecycle."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "done"
    FAILED = "failed"

    # Keep the prototype's source and wire contracts compatible until the API
    # and frontend lifecycle migration is coordinated in TASK-002/TASK-004.
    DONE = "done"


class Settings(BaseSettings):
    """Validated application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    summary_mode: Literal["demo", "openrouter"] = "demo"
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_base_url: HttpUrl = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    openrouter_max_retries: int = Field(default=1, ge=0, le=3)

    max_chunk_size: int = Field(default=8_000, ge=500, le=50_000)
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1_024, le=100 * 1024 * 1024)
    database_url: str = "sqlite:///./data/document-summary.sqlite3"
    backend_api_url: HttpUrl = "http://127.0.0.1:8000"
    container_backend_api_url: HttpUrl = "http://api:8000"

    @field_validator("openrouter_model", "database_url")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def require_live_credentials(self) -> "Settings":
        if self.summary_mode != "openrouter":
            return self

        if self.openrouter_api_key is None:
            raise ValueError("OPENROUTER_API_KEY is required when SUMMARY_MODE=openrouter")

        key = self.openrouter_api_key.get_secret_value().strip()
        placeholders = {
            "",
            "changeme",
            "replace-me",
            "replace_me",
            "your-api-key",
            "your_api_key",
            "your_openrouter_api_key",
        }
        if key.lower() in placeholders or key.lower().startswith("your-"):
            raise ValueError("OPENROUTER_API_KEY must be a real key when SUMMARY_MODE=openrouter")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


SETTINGS = get_settings()

# Compatibility constants for the prototype modules. New code should receive a
# Settings instance rather than importing these values directly.
MAX_CHUNK_SIZE = SETTINGS.max_chunk_size
MAX_UPLOAD_SIZE = SETTINGS.max_upload_bytes
OPEN_ROUTER_KEY = (
    SETTINGS.openrouter_api_key.get_secret_value() if SETTINGS.openrouter_api_key else None
)
