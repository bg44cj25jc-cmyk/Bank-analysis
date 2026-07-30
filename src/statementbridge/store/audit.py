"""Append-only audit log.

The mockup is explicit that this list is immutable and visible to the partner,
with "no delete path anywhere in the UI". That guarantee is worth nothing if it
lives only in the UI, so it is enforced here: this module offers ``append`` and
two readers, and no update or delete of an audit line exists at any layer. A
future caller cannot quietly weaken it without adding a method, which shows up
in review.

Every override of a failed reconciliation, every bulk reassignment and every
learned rule lands here with the row ids it touched, so a partner can ask "who
changed this figure, and why" and get an answer.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client       TEXT NOT NULL,
    bank_key     TEXT NOT NULL,
    account_no   TEXT NOT NULL DEFAULT '',
    fy           TEXT NOT NULL DEFAULT '',
    pdf_path     TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'scanned',
    status       TEXT NOT NULL DEFAULT 'queued',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id    INTEGER REFERENCES jobs(id),
    ts        TEXT NOT NULL,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    detail    TEXT NOT NULL DEFAULT '',
    row_ids   TEXT NOT NULL DEFAULT '[]',
    severity  TEXT NOT NULL DEFAULT 'info'
);

CREATE INDEX IF NOT EXISTS audit_job ON audit(job_id, id);
"""

#: Severity drives the colour bar in the drawer: gold for classification work,
#: red for an override. Anything else is neutral.
SEVERITY_INFO = "info"
SEVERITY_CLASSIFY = "classify"
SEVERITY_OVERRIDE = "override"

ACTION_OVERRIDE = "OVERRIDE"
ACTION_RULE_CREATED = "RULE_CREATED"
ACTION_BULK_REASSIGN = "BULK_REASSIGN"
ACTION_CATEGORY_SET = "CATEGORY_SET"
ACTION_HEADER_EDIT = "HEADER_EDIT"
ACTION_JOB_PARSED = "JOB_PARSED"
ACTION_EXPORTED = "EXPORTED"


@dataclass(slots=True, frozen=True)
class AuditLine:
    id: int
    job_id: int | None
    ts: datetime
    actor: str
    action: str
    detail: str
    row_ids: tuple[int, ...] = ()
    severity: str = SEVERITY_INFO


@dataclass(slots=True)
class Job:
    client: str
    bank_key: str
    pdf_path: str
    account_no: str = ""
    fy: str = ""
    source: str = "scanned"
    status: str = "queued"
    id: int | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AuditStore:
    """SQLite-backed job and audit storage."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    # --- jobs -----------------------------------------------------------

    def add_job(self, job: Job) -> Job:
        timestamp = _now()
        cursor = self._connection.execute(
            "INSERT INTO jobs (client, bank_key, account_no, fy, pdf_path, source,"
            " status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (job.client, job.bank_key, job.account_no, job.fy, job.pdf_path,
             job.source, job.status, timestamp, timestamp),
        )
        self._connection.commit()
        job.id = int(cursor.lastrowid)
        return job

    def set_status(self, job_id: int, status: str) -> None:
        self._connection.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), job_id),
        )
        self._connection.commit()

    def jobs(self) -> list[Job]:
        rows = self._connection.execute(
            "SELECT * FROM jobs ORDER BY id DESC"
        ).fetchall()
        return [
            Job(
                id=row["id"], client=row["client"], bank_key=row["bank_key"],
                account_no=row["account_no"], fy=row["fy"], pdf_path=row["pdf_path"],
                source=row["source"], status=row["status"],
            )
            for row in rows
        ]

    # --- audit: append and read only ------------------------------------

    def append(
        self,
        *,
        actor: str,
        action: str,
        detail: str = "",
        job_id: int | None = None,
        row_ids: Iterable[int] = (),
        severity: str = SEVERITY_INFO,
    ) -> AuditLine:
        ids = tuple(int(value) for value in row_ids)
        timestamp = _now()
        cursor = self._connection.execute(
            "INSERT INTO audit (job_id, ts, actor, action, detail, row_ids, severity)"
            " VALUES (?,?,?,?,?,?,?)",
            (job_id, timestamp, actor, action, detail, json.dumps(list(ids)), severity),
        )
        self._connection.commit()
        return AuditLine(
            id=int(cursor.lastrowid), job_id=job_id,
            ts=datetime.fromisoformat(timestamp), actor=actor, action=action,
            detail=detail, row_ids=ids, severity=severity,
        )

    def append_override(
        self, *, actor: str, job_id: int | None, variance: Decimal, reason: str
    ) -> AuditLine:
        """Record an export forced past a failed reconciliation.

        The variance is written alongside the reason so the partner sees the
        size of what was waved through, not merely that something was.
        """
        from ..money import format_indian

        return self.append(
            actor=actor, action=ACTION_OVERRIDE, job_id=job_id,
            detail=f"variance {format_indian(variance)} — {reason}",
            severity=SEVERITY_OVERRIDE,
        )

    def lines(self, job_id: int | None = None, limit: int = 500) -> list[AuditLine]:
        if job_id is None:
            rows = self._connection.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM audit WHERE job_id = ? ORDER BY id DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        return [
            AuditLine(
                id=row["id"], job_id=row["job_id"],
                ts=datetime.fromisoformat(row["ts"]), actor=row["actor"],
                action=row["action"], detail=row["detail"],
                row_ids=tuple(json.loads(row["row_ids"])), severity=row["severity"],
            )
            for row in rows
        ]

    def count(self, job_id: int | None = None) -> int:
        if job_id is None:
            row = self._connection.execute("SELECT COUNT(*) AS n FROM audit").fetchone()
        else:
            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM audit WHERE job_id = ?", (job_id,)
            ).fetchone()
        return int(row["n"])
