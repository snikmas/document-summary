import json

import httpx
import pytest

from backend.config import Settings
from backend.pipeline.llm import (
    DemoProvider,
    OpenRouterProvider,
    ProviderError,
    build_provider,
    count_words,
    get_summary_from_llm,
)


def live_settings(**overrides: object) -> Settings:
    values = {
        "summary_mode": "openrouter",
        "openrouter_api_key": "sk-or-offline-test",
        "openrouter_model": "example/requested-model",
        "openrouter_max_retries": 0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def openrouter_response(
    *,
    content: str | None = None,
    status_code: int = 200,
    routed_model: str = "example/routed-model",
) -> httpx.Response:
    if content is None:
        content = json.dumps(
            {
                "summary": "A useful summary.",
                "key_points": ["First point", "Second point"],
                "language": "English",
            }
        )
    return httpx.Response(
        status_code,
        json={
            "model": routed_model,
            "choices": [{"message": {"content": content}}],
        },
    )


def provider_for(
    handler,
    **setting_overrides: object,
) -> OpenRouterProvider:
    return OpenRouterProvider(
        live_settings(**setting_overrides),
        transport=httpx.MockTransport(handler),
    )


def test_demo_provider_is_deterministic_useful_and_network_free(monkeypatch) -> None:
    def reject_network(*args, **kwargs):
        raise AssertionError("demo provider attempted network I/O")

    monkeypatch.setattr(httpx.Client, "post", reject_network)
    provider = build_provider(Settings(_env_file=None))
    text = "Quarterly revenue increased by ten percent. Support wait time fell. Hiring stayed flat."

    first = provider.summarize(text, input_format="txt")
    second = provider.summarize(text, input_format="txt")

    assert isinstance(provider, DemoProvider)
    assert first == second
    assert first.language == "English"
    assert first.word_count == count_words(text) == 13
    assert first.metadata.mode == "demo"
    assert first.metadata.provider == "local"
    assert first.metadata.input_format == "txt"
    assert first.metadata.processing_time_ms == 0


def test_multichunk_flow_keeps_local_source_count_and_metadata() -> None:
    chunks = ["Alpha beta gamma.", "Delta epsilon."]

    result = get_summary_from_llm(chunks, provider=DemoProvider(), input_format="pdf")

    assert result.word_count == 5
    assert result.metadata.chunk_count == 2
    assert result.metadata.input_format == "pdf"


def test_openrouter_success_parses_fenced_json_and_uses_local_metadata() -> None:
    seen_request: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request.update(json.loads(request.content))
        content = """Here is the result:
```json
{"summary":"Safe summary.","key_points":["One"],"language":"English"}
```"""
        return openrouter_response(content=content)

    result = provider_for(handler).summarize(
        "one two three four",
        source_word_count=99,
        input_format="docx",
        chunk_count=3,
    )

    assert result.summary == "Safe summary."
    assert result.word_count == 99
    assert result.metadata.provider == "openrouter"
    assert result.metadata.requested_model == "example/requested-model"
    assert result.metadata.routed_model == "example/routed-model"
    assert result.metadata.input_format == "docx"
    assert result.metadata.chunk_count == 3
    assert "word count" not in seen_request["messages"][0]["content"].lower()


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "provider_authentication"),
        (402, "provider_rate_limited"),
        (429, "provider_rate_limited"),
        (400, "provider_request_rejected"),
    ],
)
def test_openrouter_maps_non_retryable_statuses(status_code: int, expected_code: str) -> None:
    provider = provider_for(lambda request: openrouter_response(status_code=status_code))

    with pytest.raises(ProviderError) as raised:
        provider.summarize("valid source")

    assert raised.value.code == expected_code
    assert raised.value.retryable is False


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "{}",
        '{"summary":"","key_points":[],"language":"English"}',
    ],
)
def test_openrouter_rejects_malformed_structured_output(content: str) -> None:
    provider = provider_for(lambda request: openrouter_response(content=content))

    with pytest.raises(ProviderError) as raised:
        provider.summarize("valid source")

    assert raised.value.code == "provider_malformed_response"


def test_openrouter_retries_server_error_with_a_strict_bound() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return openrouter_response(status_code=503)
        return openrouter_response()

    result = provider_for(handler, openrouter_max_retries=2).summarize("valid source")

    assert result.summary == "A useful summary."
    assert calls == 3


def test_openrouter_maps_timeout_after_bounded_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("offline simulated timeout", request=request)

    provider = provider_for(handler, openrouter_max_retries=1)

    with pytest.raises(ProviderError) as raised:
        provider.summarize("valid source")

    assert raised.value.code == "provider_timeout"
    assert calls == 2


def test_provider_rejects_empty_input_before_request() -> None:
    provider = provider_for(lambda request: openrouter_response())

    with pytest.raises(ValueError, match="empty text"):
        provider.summarize("  \n ")
