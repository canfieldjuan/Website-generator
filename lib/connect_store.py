"""Durable Local Connect v2 job and provider identity storage."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JobConflict(RuntimeError):
    """A caller reused a job ID for a different request."""


class ProviderBusy(RuntimeError):
    """The single-worker provider already owns another active job."""


@dataclass(frozen=True)
class StoredJob:
    job_id: str
    request_hash: str
    request: dict[str, Any]
    input_artifact: dict[str, Any]
    input_bytes: bytes
    status: str
    created_at: str
    updated_at: str
    output_artifact_id: str | None = None
    output_display_name: str | None = None
    output_bytes: bytes | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_retryable: bool | None = None


class ConnectStore:
    """SQLite-backed ownership for one durable provider namespace."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.path.parent.chmod(0o700)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS connect_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS connect_jobs (
                    job_id TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    input_artifact_json TEXT NOT NULL,
                    input_bytes BLOB NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('accepted', 'processing', 'completed', 'failed')
                    ),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    output_artifact_id TEXT,
                    output_display_name TEXT,
                    output_bytes BLOB,
                    error_code TEXT,
                    error_message TEXT,
                    error_retryable INTEGER CHECK (
                        error_retryable IS NULL OR error_retryable IN (0, 1)
                    ),
                    CHECK (
                        (status = 'completed'
                         AND output_artifact_id IS NOT NULL
                         AND output_display_name IS NOT NULL
                         AND output_bytes IS NOT NULL
                         AND error_code IS NULL
                         AND error_message IS NULL
                         AND error_retryable IS NULL)
                        OR
                        (status = 'failed'
                         AND output_artifact_id IS NULL
                         AND output_display_name IS NULL
                         AND output_bytes IS NULL
                         AND error_code IS NOT NULL
                         AND error_message IS NOT NULL
                         AND error_retryable IS NOT NULL)
                        OR
                        (status IN ('accepted', 'processing')
                         AND output_artifact_id IS NULL
                         AND output_display_name IS NULL
                         AND output_bytes IS NULL
                         AND error_code IS NULL
                         AND error_message IS NULL
                         AND error_retryable IS NULL)
                    )
                );

                CREATE UNIQUE INDEX IF NOT EXISTS one_active_connect_job
                    ON connect_jobs ((1))
                    WHERE status IN ('accepted', 'processing');
                """
            )
        self.path.chmod(0o600)

    def instance_id(self) -> str:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM connect_metadata WHERE key = 'instance_id'"
            ).fetchone()
            if row is not None:
                instance_id = str(row["value"])
                try:
                    parsed = uuid.UUID(instance_id)
                except ValueError as exc:
                    raise RuntimeError("Stored Connect instance identity is invalid.") from exc
                if parsed.version != 4 or str(parsed) != instance_id:
                    raise RuntimeError("Stored Connect instance identity is invalid.")
                return instance_id
            instance_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO connect_metadata (key, value) VALUES ('instance_id', ?)",
                (instance_id,),
            )
            return instance_id

    def accept(
        self,
        *,
        request: dict[str, Any],
        request_hash: str,
        input_bytes: bytes,
    ) -> tuple[StoredJob, bool]:
        job_id = request["job_id"]
        artifact = request["inputs"][0]
        timestamp = utc_now()
        request_json = canonical_json(request)
        artifact_json = canonical_json(artifact)

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM connect_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise JobConflict(
                        "The job ID already belongs to a different request."
                    )
                return _row_to_job(existing), False

            try:
                connection.execute(
                    """
                    INSERT INTO connect_jobs (
                        job_id, request_hash, request_json, input_artifact_json,
                        input_bytes, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'accepted', ?, ?)
                    """,
                    (
                        job_id,
                        request_hash,
                        request_json,
                        artifact_json,
                        input_bytes,
                        timestamp,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "one_active_connect_job" in str(exc) or "UNIQUE constraint" in str(exc):
                    raise ProviderBusy(
                        "The provider is already processing another job."
                    ) from exc
                raise
            row = connection.execute(
                "SELECT * FROM connect_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("Accepted Connect job could not be reloaded.")
            return _row_to_job(row), True

    def get(self, job_id: str) -> StoredJob | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM connect_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return _row_to_job(row) if row is not None else None

    def accepted_jobs(self) -> list[StoredJob]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM connect_jobs
                WHERE status = 'accepted'
                ORDER BY created_at, job_id
                """
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def mark_processing(self, job_id: str) -> bool:
        timestamp = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE connect_jobs
                SET status = 'processing', updated_at = ?
                WHERE job_id = ? AND status = 'accepted'
                """,
                (timestamp, job_id),
            )
        return cursor.rowcount == 1

    def complete(
        self,
        job_id: str,
        *,
        artifact_id: str,
        display_name: str,
        output_bytes: bytes,
    ) -> bool:
        timestamp = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE connect_jobs
                SET status = 'completed', updated_at = ?,
                    output_artifact_id = ?, output_display_name = ?,
                    output_bytes = ?
                WHERE job_id = ? AND status = 'processing'
                """,
                (timestamp, artifact_id, display_name, output_bytes, job_id),
            )
        return cursor.rowcount == 1

    def fail(
        self,
        job_id: str,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> bool:
        timestamp = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE connect_jobs
                SET status = 'failed', updated_at = ?, error_code = ?,
                    error_message = ?, error_retryable = ?
                WHERE job_id = ? AND status IN ('accepted', 'processing')
                """,
                (timestamp, code, message, int(retryable), job_id),
            )
        return cursor.rowcount == 1

    def reconcile_interrupted(self) -> int:
        """Make ambiguous in-flight delivery explicit after process restart."""
        timestamp = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE connect_jobs
                SET status = 'failed', updated_at = ?,
                    error_code = 'PROVIDER_INTERRUPTED',
                    error_message = 'The provider stopped while generating this job.',
                    error_retryable = 1
                WHERE status = 'processing'
                """,
                (timestamp,),
            )
        return cursor.rowcount


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _row_to_job(row: sqlite3.Row) -> StoredJob:
    retryable = row["error_retryable"]
    return StoredJob(
        job_id=str(row["job_id"]),
        request_hash=str(row["request_hash"]),
        request=json.loads(row["request_json"]),
        input_artifact=json.loads(row["input_artifact_json"]),
        input_bytes=bytes(row["input_bytes"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        output_artifact_id=row["output_artifact_id"],
        output_display_name=row["output_display_name"],
        output_bytes=(
            bytes(row["output_bytes"]) if row["output_bytes"] is not None else None
        ),
        error_code=row["error_code"],
        error_message=row["error_message"],
        error_retryable=(bool(retryable) if retryable is not None else None),
    )
