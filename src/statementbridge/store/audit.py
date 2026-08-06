"""The audit trail.

Overrides, header corrections and (from step 7) rule creations are written here
with the rows they touched. Nothing in it can be edited or deleted -- that is
enforced by triggers in :mod:`store.db`, not by the discipline of the callers,
because the value of the record to a partner explaining a figure to a client
lies entirely in nobody having been able to tidy it afterwards.
"""

from __future__ import annotations

import sqlite3

from .models import AuditEntry, Principal, now


def record(
    connection: sqlite3.Connection,
    principal: Principal,
    action: str,
    *,
    job_id: str | None = None,
    detail: str = "",
    reason: str = "",
) -> AuditEntry:
    entry = AuditEntry(
        at=now(),
        actor=principal.name,
        role=principal.role.value,
        action=action,
        job_id=job_id,
        detail=detail,
        reason=reason,
    )
    cursor = connection.execute(
        "INSERT INTO audit_log (at, actor, role, action, job_id, detail, reason) "
        "VALUES (?,?,?,?,?,?,?)",
        (entry.at, entry.actor, entry.role, entry.action, entry.job_id,
         entry.detail, entry.reason),
    )
    entry.id = cursor.lastrowid
    return entry


def for_job(connection: sqlite3.Connection, job_id: str) -> list[AuditEntry]:
    rows = connection.execute(
        "SELECT id, at, actor, role, action, job_id, detail, reason "
        "FROM audit_log WHERE job_id = ? ORDER BY id",
        (job_id,),
    ).fetchall()
    return [
        AuditEntry(
            id=row["id"], at=row["at"], actor=row["actor"], role=row["role"],
            action=row["action"], job_id=row["job_id"], detail=row["detail"],
            reason=row["reason"],
        )
        for row in rows
    ]


def recent(connection: sqlite3.Connection, *, limit: int = 100) -> list[AuditEntry]:
    rows = connection.execute(
        "SELECT id, at, actor, role, action, job_id, detail, reason "
        "FROM audit_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        AuditEntry(
            id=row["id"], at=row["at"], actor=row["actor"], role=row["role"],
            action=row["action"], job_id=row["job_id"], detail=row["detail"],
            reason=row["reason"],
        )
        for row in rows
    ]
