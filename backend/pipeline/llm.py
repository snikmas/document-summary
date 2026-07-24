import json
import logging
import re
import time
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.config import Settings, get_settings
from backend.models import DocumentSummary, ProcessingMetadata

log = logging.getLogger("pipeline.llm")

SYSTEM_PROMPT = """You summarize documents. Return exactly one JSON object:
{"summary":"2-3 useful sentences","key_points":["point 1","point 2"],"language":"English"}
Use the document's language. Return only the three requested fields."""


class ProviderError(RuntimeError):
    """Client-safe provider failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ProviderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1, max_length=10)
    language: str = Field(min_length=1)

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


class SummaryProvider(Protocol):
    def summarize(
        self,
        text: str,
        *,
        source_word_count: int | None = None,
        input_format: str = "unknown",
        chunk_count: int = 1,
    ) -> DocumentSummary: ...


def count_words(text: str) -> int:
    """Return a provider-independent Unicode word count."""

    return len(re.findall(r"\w+(?:['’\-]\w+)*", text, flags=re.UNICODE))


def _require_source(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        raise ValueError("Cannot summarize empty text")
    return normalized


def _detect_language(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text):
        return "Chinese"
    if re.search(r"[\u0400-\u04ff]", text):
        return "Russian"
    return "English"


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    return [part.strip() for part in parts if part.strip()]


class DemoProvider:
    """A deterministic, local provider for portfolio demos and tests."""

    model_name = "deterministic-extractive-v1"

    def summarize(
        self,
        text: str,
        *,
        source_word_count: int | None = None,
        input_format: str = "unknown",
        chunk_count: int = 1,
    ) -> DocumentSummary:
        normalized = _require_source(text)
        sentences = _sentences(normalized) or [normalized]
        selected = sentences[:3]
        summary = " ".join(selected[:2])[:800].strip()
        key_points = [sentence[:300].strip() for sentence in selected if sentence.strip()]

        return DocumentSummary(
            summary=summary,
            key_points=key_points,
            language=_detect_language(normalized),
            word_count=source_word_count or count_words(normalized),
            metadata=ProcessingMetadata(
                mode="demo",
                provider="local",
                requested_model=self.model_name,
                routed_model=self.model_name,
                input_format=input_format,
                chunk_count=chunk_count,
                # Demo output is a reproducible fixture, so wall-clock timing is
                # intentionally reserved for live providers.
                processing_time_ms=0,
            ),
        )


def _extract_json_object(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        closing_fence = content.rfind("```")
        if first_newline != -1 and closing_fence > first_newline:
            content = content[first_newline + 1 : closing_fence].strip()

    object_start = content.find("{")
    if object_start == -1:
        raise ValueError("response does not contain a JSON object")
    value, _ = json.JSONDecoder().raw_decode(content[object_start:])
    if not isinstance(value, dict):
        raise ValueError("response JSON must be an object")
    return value


class OpenRouterProvider:
    """OpenRouter's OpenAI-compatible API behind the shared provider contract."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if settings.summary_mode != "openrouter" or settings.openrouter_api_key is None:
            raise ProviderError(
                "provider_not_configured",
                "OpenRouter mode requires a valid OPENROUTER_API_KEY.",
            )
        self.settings = settings
        self.transport = transport

    def summarize(
        self,
        text: str,
        *,
        source_word_count: int | None = None,
        input_format: str = "unknown",
        chunk_count: int = 1,
    ) -> DocumentSummary:
        started = time.monotonic()
        normalized = _require_source(text)
        word_count = source_word_count or count_words(normalized)
        attempts = self.settings.openrouter_max_retries + 1

        for attempt in range(attempts):
            try:
                data = self._request(normalized)
                output, routed_model = self._parse_response(data)
                return DocumentSummary(
                    **output.model_dump(),
                    word_count=word_count,
                    metadata=ProcessingMetadata(
                        mode="openrouter",
                        provider="openrouter",
                        requested_model=self.settings.openrouter_model,
                        routed_model=routed_model,
                        input_format=input_format,
                        chunk_count=chunk_count,
                        processing_time_ms=max(0, round((time.monotonic() - started) * 1_000)),
                    ),
                )
            except ProviderError as exc:
                if not exc.retryable or attempt == attempts - 1:
                    raise

        raise AssertionError("provider retry loop exited unexpectedly")

    def _request(self, text: str) -> dict[str, Any]:
        key = self.settings.openrouter_api_key
        assert key is not None  # validated in __init__
        try:
            with httpx.Client(
                timeout=self.settings.openrouter_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    f"{str(self.settings.openrouter_base_url).rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.openrouter_model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": text},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "provider_timeout",
                "The AI service timed out. Please try again.",
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                "provider_unavailable",
                "The AI service could not be reached. Please try again.",
                retryable=True,
            ) from exc

        if response.status_code == 401:
            raise ProviderError(
                "provider_authentication",
                "OpenRouter authentication failed. Check the configured API key.",
            )
        if response.status_code in {402, 429}:
            raise ProviderError(
                "provider_rate_limited",
                "OpenRouter has no available quota or is rate limited. Please try again later.",
            )
        if response.status_code >= 500:
            raise ProviderError(
                "provider_unavailable",
                "The AI service is temporarily unavailable. Please try again later.",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ProviderError(
                "provider_request_rejected",
                "The AI service rejected the summarization request.",
            )

        try:
            value = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "provider_malformed_response",
                "The AI service returned an invalid response.",
                retryable=True,
            ) from exc
        if not isinstance(value, dict):
            raise ProviderError(
                "provider_malformed_response",
                "The AI service returned an invalid response.",
                retryable=True,
            )
        return value

    def _parse_response(self, data: dict[str, Any]) -> tuple[ProviderOutput, str | None]:
        try:
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty response content")
            output = ProviderOutput.model_validate(_extract_json_object(content))
            routed_model = data.get("model")
            if routed_model is not None and not isinstance(routed_model, str):
                raise ValueError("invalid routed model")
            return output, routed_model
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            raise ProviderError(
                "provider_malformed_response",
                "The AI service returned an invalid structured summary.",
                retryable=True,
            ) from exc


def build_provider(
    settings: Settings | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> SummaryProvider:
    settings = settings or get_settings()
    if settings.summary_mode == "demo":
        return DemoProvider()
    return OpenRouterProvider(settings, transport=transport)


def call_llm(
    text: str,
    *,
    provider: SummaryProvider | None = None,
    source_word_count: int | None = None,
    input_format: str = "unknown",
    chunk_count: int = 1,
) -> DocumentSummary:
    """Compatibility entrypoint backed by the selected provider."""

    provider = provider or build_provider()
    return provider.summarize(
        text,
        source_word_count=source_word_count,
        input_format=input_format,
        chunk_count=chunk_count,
    )


def get_summary_from_llm(
    text_chunks: list[str],
    *,
    provider: SummaryProvider | None = None,
    input_format: str = "unknown",
) -> DocumentSummary:
    """Summarize chunks without trusting model-generated counts or metadata."""

    if not text_chunks or any(not chunk.strip() for chunk in text_chunks):
        raise ValueError("At least one non-empty text chunk is required")

    provider = provider or build_provider()
    source_word_count = count_words("\n\n".join(text_chunks))
    chunk_count = len(text_chunks)
    if chunk_count == 1:
        return call_llm(
            text_chunks[0],
            provider=provider,
            source_word_count=source_word_count,
            input_format=input_format,
            chunk_count=1,
        )

    partials = [
        call_llm(
            chunk,
            provider=provider,
            source_word_count=count_words(chunk),
            input_format=input_format,
        )
        for chunk in text_chunks
    ]
    compact_merge_input = "\n".join(
        f"Summary: {partial.summary}\nKey points: {'; '.join(partial.key_points)}"
        for partial in partials
    )
    return call_llm(
        compact_merge_input,
        provider=provider,
        source_word_count=source_word_count,
        input_format=input_format,
        chunk_count=chunk_count,
    )
