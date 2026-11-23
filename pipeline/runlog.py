"""Record pipeline runs and step timing in the CardPulse SQLite database."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import sqlite3
import time

import config


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@contextmanager
def _connect():
    with closing(sqlite3.connect(config.DB_PATH, timeout=30)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection


def start_run(trigger: str, run_id: str | None = None) -> str:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = (config.SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    with _connect() as connection:
        connection.executescript(schema)

    while True:
        started_at = _timestamp()
        candidate = run_id
        if candidate is None:
            stamp = datetime.fromisoformat(started_at).strftime("%Y%m%dT%H%M%SZ")
            candidate = f"{trigger}-{stamp}"
        with _connect() as connection:
            inserted = connection.execute(
                """
                INSERT INTO pipeline_runs (run_id, trigger, started_at, status)
                VALUES (?, ?, ?, 'running')
                ON CONFLICT (run_id) DO NOTHING
                """,
                (candidate, trigger, started_at),
            ).rowcount
        if inserted or run_id is not None:
            return candidate
        # Generated IDs have second precision. Let independent runs keep their own rows.
        time.sleep(0.1)


def start_step(run_id: str, step: str) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO pipeline_steps (run_id, step, started_at, status)
            VALUES (?, ?, ?, 'running')
            ON CONFLICT (run_id, step) DO UPDATE SET
                started_at = excluded.started_at, status = excluded.status,
                finished_at = NULL, duration_s = NULL, message = NULL
            """,
            (run_id, step, _timestamp()),
        )


def finish_step(run_id: str, step: str, status: str, message: str | None = None) -> None:
    with _connect() as connection:
        (started_at,) = connection.execute(
            "SELECT started_at FROM pipeline_steps WHERE run_id = ? AND step = ?",
            (run_id, step),
        ).fetchone()
        finished_at = _timestamp()
        duration = datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
        stderr_tail = message[-500:] if message is not None else None
        connection.execute(
            """
            UPDATE pipeline_steps
            SET status = ?, finished_at = ?, duration_s = ?, message = ?
            WHERE run_id = ? AND step = ?
            """,
            (status, finished_at, duration.total_seconds(), stderr_tail, run_id, step),
        )


def finish_run(run_id: str, status: str) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE pipeline_runs SET status = ?, finished_at = ? WHERE run_id = ?",
            (status, _timestamp(), run_id),
        )
