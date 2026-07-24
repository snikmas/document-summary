from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.config import Status


class ProcessingMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["demo", "openrouter"]
    provider: str = Field(min_length=1)
    requested_model: str = Field(min_length=1)
    routed_model: str | None = None
    input_format: str = Field(default="unknown", min_length=1)
    chunk_count: int = Field(default=1, ge=1)
    processing_time_ms: int = Field(default=0, ge=0)

    @field_validator("provider", "requested_model", "routed_model", "input_format")
    @classmethod
    def trim_metadata(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("metadata text must not be empty")
        return value


class DocumentSummary(BaseModel):
    """Trusted application result; counts and metadata are supplied locally."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1, max_length=10)
    language: str = Field(min_length=1)
    word_count: int = Field(ge=1)
    metadata: ProcessingMetadata

    @field_validator("summary", "language")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        return value

    @field_validator("key_points")
    @classmethod
    def trim_key_points(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty key point is required")
        return cleaned


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class JobAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Status


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Status
    filename: str
    input_format: str
    byte_size: int = Field(gt=0)
    created_at: datetime
    updated_at: datetime
    error: ErrorDetail | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    mode: Literal["demo", "openrouter"]
