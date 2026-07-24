import pytest
from pydantic import ValidationError

from backend.config import Settings, Status


def test_status_wire_values_remain_compatible_with_existing_frontend() -> None:
    assert Status.PENDING.value == "pending"
    assert Status.PROCESSING.value == "processing"
    assert Status.COMPLETED.value == "done"
    assert Status.DONE is Status.COMPLETED
    assert Status.FAILED.value == "failed"


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_demo_mode_is_default_and_keyless() -> None:
    settings = make_settings()

    assert settings.summary_mode == "demo"
    assert settings.openrouter_api_key is None
    assert str(settings.backend_api_url) == "http://127.0.0.1:8000/"
    assert str(settings.container_backend_api_url) == "http://api:8000/"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_chunk_size", 499),
        ("max_upload_bytes", 0),
        ("openrouter_timeout_seconds", 0),
        ("openrouter_max_retries", 4),
        ("openrouter_model", "  "),
        ("database_url", ""),
    ],
)
def test_invalid_limits_and_required_text_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


@pytest.mark.parametrize(
    "key",
    [None, "", "changeme", "your-api-key", "your_openrouter_api_key"],
)
def test_live_mode_requires_non_placeholder_key(key: str | None) -> None:
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        make_settings(summary_mode="openrouter", openrouter_api_key=key)


def test_live_mode_accepts_explicit_configuration() -> None:
    settings = make_settings(
        summary_mode="openrouter",
        openrouter_api_key="sk-or-example-for-offline-test",
        openrouter_model="example/model",
        openrouter_timeout_seconds=12,
        openrouter_max_retries=2,
    )

    assert settings.summary_mode == "openrouter"
    assert settings.openrouter_api_key is not None
    assert settings.openrouter_api_key.get_secret_value() == "sk-or-example-for-offline-test"
    assert settings.openrouter_model == "example/model"
