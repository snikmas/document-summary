from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.config import Status
from backend.jobs import CorruptJobResultError, JobRepository, JobStateError
from backend.pipeline.llm import DemoProvider


def create_pending(repository: JobRepository):
    return repository.create(
        filename="report.txt",
        input_format="txt",
        byte_size=42,
        mode="demo",
        requested_model="deterministic-extractive-v1",
    )


def test_repository_persists_completed_result_across_instances(database_url: str) -> None:
    first = JobRepository(database_url)
    first.initialize()
    pending = create_pending(first)
    first.mark_processing(pending.id)
    result = DemoProvider().summarize("Revenue increased. Support improved.", input_format="txt")
    first.complete(pending.id, result)

    restarted = JobRepository(database_url)
    restarted.initialize()
    record = restarted.get(pending.id)

    assert record is not None
    assert record.status is Status.COMPLETED
    assert record.result == result
    assert record.filename == "report.txt"
    assert record.provider == "local"
    assert record.requested_model == "deterministic-extractive-v1"


def test_repository_enforces_lifecycle_transitions(database_url: str) -> None:
    repository = JobRepository(database_url)
    repository.initialize()
    pending = create_pending(repository)
    result = DemoProvider().summarize("A complete source sentence.", input_format="txt")

    with pytest.raises(JobStateError):
        repository.complete(pending.id, result)

    processing = repository.mark_processing(pending.id)
    assert processing.status is Status.PROCESSING

    with pytest.raises(JobStateError):
        repository.mark_processing(pending.id)

    completed = repository.complete(pending.id, result)
    assert completed.status is Status.COMPLETED

    with pytest.raises(JobStateError):
        repository.fail(pending.id, code="late_failure", message="Too late.")


def test_restart_resolves_only_interrupted_processing_jobs(database_url: str) -> None:
    repository = JobRepository(database_url)
    repository.initialize()
    pending = create_pending(repository)
    interrupted = create_pending(repository)
    repository.mark_processing(interrupted.id)

    assert repository.resolve_interrupted() == 1
    assert repository.get(pending.id).status is Status.PENDING  # type: ignore[union-attr]
    failed = repository.get(interrupted.id)
    assert failed is not None
    assert failed.status is Status.FAILED
    assert failed.error_code == "processing_interrupted"
    assert failed.result is None


def test_cleanup_removes_only_old_finished_records(database_url: str) -> None:
    repository = JobRepository(database_url)
    repository.initialize()
    pending = create_pending(repository)
    finished = create_pending(repository)
    repository.fail(finished.id, code="test", message="Test failure.")

    removed = repository.delete_finished_before(datetime.now(UTC) + timedelta(seconds=1))

    assert removed == 1
    assert repository.get(finished.id) is None
    assert repository.get(pending.id) is not None


def test_database_contains_no_raw_source_column(database_url: str) -> None:
    repository = JobRepository(database_url)
    repository.initialize()
    import sqlite3

    database_path = Path(database_url.removeprefix("sqlite:///"))
    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}

    assert "file_bytes" not in columns
    assert "source_text" not in columns
    assert "raw_document" not in columns


def test_repository_rejects_in_memory_database() -> None:
    with pytest.raises(ValueError, match="file-backed"):
        JobRepository("sqlite:///:memory:")


@pytest.mark.parametrize(
    "persisted_result",
    [
        "{not-json",
        '{"summary": "schema-stale"}',
        "null",
    ],
)
def test_repository_maps_corrupt_persisted_results_to_typed_error(
    database_url: str,
    persisted_result: str,
) -> None:
    repository = JobRepository(database_url)
    repository.initialize()
    job = create_pending(repository)

    import sqlite3

    database_path = Path(database_url.removeprefix("sqlite:///"))
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE jobs SET status = ?, result_json = ? WHERE id = ?",
            (Status.COMPLETED.value, persisted_result, job.id),
        )

    with pytest.raises(CorruptJobResultError, match="stored job result"):
        repository.get(job.id)
