from pathlib import Path

import pytest

from backend.config import Settings


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'jobs.sqlite3'}"


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        database_url=database_url,
        max_upload_bytes=2_048,
        max_chunk_size=500,
    )
