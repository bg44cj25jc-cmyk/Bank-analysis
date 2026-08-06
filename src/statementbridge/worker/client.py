"""The worker's side of the job protocol: plain HTTP, no database.

Everything the worker knows about a job arrives through here, and everything it
learns goes back the same way. That is the point -- a process that only speaks
HTTP does not care whether the API is a sibling container on the NAS or a
machine across the office, so moving OCR onto the desktop is a change of one
environment variable rather than a change of architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class ClaimedJob:
    id: str
    stage: str
    source_path: str
    profile_key: str | None = None
    opening: str | None = None
    closing: str | None = None
    holder: str | None = None


class ApiClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-Worker-Token": token},
            # Generous, because a result POST carries every extracted row and
            # the API writes them all before answering. Nothing here is a
            # user-facing request that anyone is waiting on.
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def claim(self, worker: str) -> ClaimedJob | None:
        """Ask for work. ``None`` means the queue is empty, not that it failed."""
        response = self._client.post("/internal/jobs/claim", json={"worker": worker})
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        payload = response.json()
        if payload is None:
            return None
        return ClaimedJob(**payload)

    def progress(self, job_id: str, done: int, total: int) -> None:
        """Best effort: a dropped progress ping must never fail the job."""
        try:
            self._client.post(
                f"/internal/jobs/{job_id}/progress", json={"done": done, "total": total}
            )
        except httpx.HTTPError:
            pass

    def header(self, job_id: str, payload: dict[str, Any]) -> None:
        self._client.post(f"/internal/jobs/{job_id}/header", json=payload).raise_for_status()

    def result(self, job_id: str, payload: dict[str, Any]) -> None:
        self._client.post(f"/internal/jobs/{job_id}/result", json=payload).raise_for_status()

    def failed(self, job_id: str, error: str) -> None:
        try:
            self._client.post(
                f"/internal/jobs/{job_id}/failed", json={"error": error[:2000]}
            ).raise_for_status()
        except httpx.HTTPError:
            pass
