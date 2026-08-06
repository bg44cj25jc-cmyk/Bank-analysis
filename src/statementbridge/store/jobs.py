"""Job records, and the queue they double as.

The claim is the only interesting query. It has to hand exactly one job to
exactly one worker even when several ask at the same moment, which SQLite gives
for free -- there is a single writer, and ``UPDATE ... WHERE id = (SELECT ...
LIMIT 1) RETURNING`` is one statement, so two workers cannot both win the same
row. A second claimant simply matches nothing and is told to wait.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Iterable

from ..parse.frame import FRAME_COLUMNS
from .models import Job, JobState, Stage, now

_COLUMNS = (
    "id, created_at, updated_at, filename, state, stage, profile_key, "
    "quality_verdict, quality_json, account_no, holder, opening, closing, "
    "variance, page_count, row_count, unresolved, reconciled, chain_json, "
    "error, claimed_at, claimed_by, progress_done, progress_total"
)


def _to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        filename=row["filename"],
        state=JobState(row["state"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        stage=Stage(row["stage"]) if row["stage"] else None,
        profile_key=row["profile_key"],
        quality_verdict=row["quality_verdict"],
        quality=json.loads(row["quality_json"]) if row["quality_json"] else None,
        account_no=row["account_no"],
        holder=row["holder"],
        opening=row["opening"],
        closing=row["closing"],
        variance=row["variance"],
        page_count=row["page_count"],
        row_count=row["row_count"],
        unresolved=row["unresolved"],
        reconciled=None if row["reconciled"] is None else bool(row["reconciled"]),
        chain=json.loads(row["chain_json"]) if row["chain_json"] else None,
        error=row["error"],
        claimed_at=row["claimed_at"],
        claimed_by=row["claimed_by"],
        progress_done=row["progress_done"],
        progress_total=row["progress_total"],
    )


def create(
    connection: sqlite3.Connection,
    *,
    filename: str,
    state: JobState,
    stage: Stage | None,
    quality_verdict: str,
    quality: dict[str, Any],
) -> Job:
    job_id = uuid.uuid4().hex
    stamp = now()
    connection.execute(
        "INSERT INTO jobs (id, created_at, updated_at, filename, state, stage, "
        "quality_verdict, quality_json) VALUES (?,?,?,?,?,?,?,?)",
        (
            job_id, stamp, stamp, filename, state.value,
            stage.value if stage else None, quality_verdict, json.dumps(quality),
        ),
    )
    return get(connection, job_id)


def get(connection: sqlite3.Connection, job_id: str) -> Job | None:
    row = connection.execute(
        f"SELECT {_COLUMNS} FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return _to_job(row) if row else None


def listing(
    connection: sqlite3.Connection,
    *,
    state: JobState | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Job], int]:
    where, params = "", []
    if state is not None:
        where, params = "WHERE state = ?", [state.value]

    total = connection.execute(
        f"SELECT COUNT(*) FROM jobs {where}", params
    ).fetchone()[0]
    rows = connection.execute(
        f"SELECT {_COLUMNS} FROM jobs {where} ORDER BY created_at DESC "
        "LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [_to_job(row) for row in rows], total


def update(connection: sqlite3.Connection, job_id: str, **fields: Any) -> Job | None:
    """Patch named columns. Enum values are unwrapped; dicts are JSON-encoded."""
    if not fields:
        return get(connection, job_id)

    assignments, params = [], []
    for column, value in fields.items():
        if hasattr(value, "value"):          # JobState / Stage
            value = value.value
        elif isinstance(value, (dict, list)):
            value = json.dumps(value)
        elif isinstance(value, bool):
            value = int(value)
        assignments.append(f"{column} = ?")
        params.append(value)

    assignments.append("updated_at = ?")
    params.append(now())
    params.append(job_id)
    connection.execute(
        f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?", params
    )
    return get(connection, job_id)


def claim(connection: sqlite3.Connection, *, worker: str) -> Job | None:
    """Hand the oldest queued job to one worker, or return None.

    One statement, so concurrent claimants cannot collide: the loser's subquery
    selects a row that is no longer QUEUED by the time it writes, matches
    nothing, and returns None.
    """
    row = connection.execute(
        "UPDATE jobs SET state = ?, claimed_at = ?, claimed_by = ?, updated_at = ? "
        "WHERE id = (SELECT id FROM jobs WHERE state = ? ORDER BY created_at LIMIT 1) "
        f"RETURNING {_COLUMNS}",
        (JobState.RUNNING.value, now(), worker, now(), JobState.QUEUED.value),
    ).fetchone()
    return _to_job(row) if row else None


def requeue_stale(connection: sqlite3.Connection, *, before: str) -> int:
    """Return jobs abandoned by a worker that died mid-run to the queue.

    Without this a crashed or restarted worker strands its job in RUNNING for
    ever, and the queue quietly stops draining.
    """
    cursor = connection.execute(
        "UPDATE jobs SET state = ?, claimed_at = NULL, claimed_by = NULL, updated_at = ? "
        "WHERE state = ? AND claimed_at < ?",
        (JobState.QUEUED.value, now(), JobState.RUNNING.value, before),
    )
    return cursor.rowcount


# --- extracted rows ------------------------------------------------------


def save_rows(
    connection: sqlite3.Connection, job_id: str, records: Iterable[dict[str, Any]]
) -> int:
    """Replace a job's rows. Payloads are JSON with money already stringified."""
    connection.execute("DELETE FROM job_rows WHERE job_id = ?", (job_id,))
    payload = [
        (job_id, index, json.dumps(record))
        for index, record in enumerate(records)
    ]
    connection.executemany(
        "INSERT INTO job_rows (job_id, idx, payload) VALUES (?,?,?)", payload
    )
    return len(payload)


def rows(
    connection: sqlite3.Connection, job_id: str, *, limit: int = 200, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    total = connection.execute(
        "SELECT COUNT(*) FROM job_rows WHERE job_id = ?", (job_id,)
    ).fetchone()[0]
    found = connection.execute(
        "SELECT payload FROM job_rows WHERE job_id = ? ORDER BY idx LIMIT ? OFFSET ?",
        (job_id, limit, offset),
    ).fetchall()
    return [json.loads(row["payload"]) for row in found], total


def record_of(txn) -> dict[str, Any]:
    """One transaction as a transportable record.

    Every Decimal becomes a string and every date an ISO day. Serialising a
    Decimal as a JSON number would hand it to the next parser as a float, which
    is precisely the drift ``money.py`` exists to prevent -- and the client's own
    workbook already shows what that looks like.
    """
    record = txn.as_record()
    out: dict[str, Any] = {}
    for column in FRAME_COLUMNS:
        value = record.get(column)
        if value is None:
            out[column] = None
        elif hasattr(value, "isoformat"):
            out[column] = value.isoformat()
        elif isinstance(value, (int, float, str, bool)):
            out[column] = value
        else:                      # Decimal, RowState, anything else
            out[column] = str(value)
    return out
