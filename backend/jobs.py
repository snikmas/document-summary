import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from pydantic import ValidationError

from backend.config import Status
from backend.models import DocumentSummary


class JobStateError(RuntimeError):
    """Raised when a caller attempts an invalid lifecycle transition."""


class CorruptJobResultError(RuntimeError):
    """Raised when a persisted result no longer matches the trusted result schema."""


@dataclass(frozen=True)
class JobRecord:
    id: str
    filename: str
    input_format: str
    byte_size: int
    status: Status
    created_at: datetime
    updated_at: datetime
    error_code: str | None
    error_message: str | None
    result: DocumentSummary | None
    mode: str
    provider: str | None
    requested_model: str | None
    routed_model: str | None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_database_url(database_url: str) -> str:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Only sqlite:/// database URLs are supported")
    path = database_url.removeprefix(prefix)
    if not path:
        raise ValueError("SQLite database path must not be empty")
    if path == ":memory:":
        raise ValueError("In-memory SQLite is not supported; use a file-backed database")
    return path


class JobRepository:
    """Small SQLite repository that owns all job lifecycle transitions."""

    def __init__(self, database_url: str) -> None:
        self.database_path = _parse_database_url(database_url)
        self._write_lock = Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    input_format TEXT NOT NULL,
                    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'processing', 'done', 'failed')
                    ),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    result_json TEXT,
                    mode TEXT NOT NULL,
                    provider TEXT,
                    requested_model TEXT,
                    routed_model TEXT
                )
                """
            )

    def healthcheck(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def create(
        self,
        *,
        filename: str,
        input_format: str,
        byte_size: int,
        mode: str,
        requested_model: str,
    ) -> JobRecord:
        job_id = str(uuid.uuid4())
        now = _utc_now()
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, filename, input_format, byte_size, status, created_at, updated_at,
                    mode, requested_model
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    filename,
                    input_format,
                    byte_size,
                    Status.PENDING.value,
                    now,
                    now,
                    mode,
                    requested_model,
                ),
            )
        record = self.get(job_id)
        assert record is not None
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._to_record(row) if row is not None else None

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM jobs").fetchone()
        assert row is not None
        return int(row["total"])

    def mark_processing(self, job_id: str) -> JobRecord:
        return self._transition(
            job_id,
            expected=Status.PENDING,
            target=Status.PROCESSING,
        )

    def complete(self, job_id: str, result: DocumentSummary) -> JobRecord:
        metadata = result.metadata
        return self._transition(
            job_id,
            expected=Status.PROCESSING,
            target=Status.COMPLETED,
            result_json=result.model_dump_json(),
            provider=metadata.provider,
            requested_model=metadata.requested_model,
            routed_model=metadata.routed_model,
        )

    def fail(self, job_id: str, *, code: str, message: str) -> JobRecord:
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error_code = ?, error_message = ?,
                    result_json = NULL
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    Status.FAILED.value,
                    _utc_now(),
                    code,
                    message,
                    job_id,
                    Status.PENDING.value,
                    Status.PROCESSING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise JobStateError(f"Job {job_id} cannot transition to failed")
        record = self.get(job_id)
        assert record is not None
        return record

    def resolve_interrupted(self) -> int:
        """Fail processing jobs left behind by a previous application process."""

        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error_code = ?, error_message = ?,
                    result_json = NULL
                WHERE status = ?
                """,
                (
                    Status.FAILED.value,
                    _utc_now(),
                    "processing_interrupted",
                    "Processing was interrupted by an application restart. Please upload again.",
                    Status.PROCESSING.value,
                ),
            )
            return cursor.rowcount

    def delete_finished_before(self, cutoff: datetime) -> int:
        """Provide an explicit local retention cleanup operation."""

        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM jobs WHERE status IN (?, ?) AND updated_at < ?",
                (
                    Status.COMPLETED.value,
                    Status.FAILED.value,
                    cutoff.astimezone(UTC).isoformat(),
                ),
            )
            return cursor.rowcount

    def _transition(
        self,
        job_id: str,
        *,
        expected: Status,
        target: Status,
        result_json: str | None = None,
        provider: str | None = None,
        requested_model: str | None = None,
        routed_model: str | None = None,
    ) -> JobRecord:
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error_code = NULL, error_message = NULL,
                    result_json = ?, provider = COALESCE(?, provider),
                    requested_model = COALESCE(?, requested_model), routed_model = ?
                WHERE id = ? AND status = ?
                """,
                (
                    target.value,
                    _utc_now(),
                    result_json,
                    provider,
                    requested_model,
                    routed_model,
                    job_id,
                    expected.value,
                ),
            )
            if cursor.rowcount != 1:
                raise JobStateError(
                    f"Job {job_id} cannot transition from {expected.value} to {target.value}"
                )
        record = self.get(job_id)
        assert record is not None
        return record

    @staticmethod
    def _to_record(row: sqlite3.Row) -> JobRecord:
        try:
            persisted_result = row["result_json"]
            result = (
                DocumentSummary.model_validate(json.loads(persisted_result))
                if persisted_result is not None
                else None
            )
        except (json.JSONDecodeError, TypeError, ValidationError) as exc:
            raise CorruptJobResultError("The stored job result is invalid") from exc
        return JobRecord(
            id=row["id"],
            filename=row["filename"],
            input_format=row["input_format"],
            byte_size=row["byte_size"],
            status=Status(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            error_code=row["error_code"],
            error_message=row["error_message"],
            result=result,
            mode=row["mode"],
            provider=row["provider"],
            requested_model=row["requested_model"],
            routed_model=row["routed_model"],
        )
