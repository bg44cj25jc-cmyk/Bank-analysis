"""Liveness, and enough queue state for the compose healthcheck to be useful."""

from __future__ import annotations

from fastapi import APIRouter

from ...store.models import JobState
from ..deps import ConnectionDep

router = APIRouter(tags=["health"])


@router.get("/api/v1/health")
def health(connection: ConnectionDep) -> dict[str, object]:
    counts = {
        row["state"]: row["n"]
        for row in connection.execute(
            "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"
        ).fetchall()
    }
    return {
        "status": "UP",
        "queued": counts.get(JobState.QUEUED.value, 0),
        "running": counts.get(JobState.RUNNING.value, 0),
        "jobs": sum(counts.values()),
    }
