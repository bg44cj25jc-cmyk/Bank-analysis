"""What a job is, and the vocabulary the API and the worker share.

The state machine is deliberately small, and the one thing worth explaining is
why there are two queued stages rather than one.

Capture quality is judged in the upload request itself: it costs a third of a
second and it is the entire point of the gate that nobody waits to hear the file
was hopeless. But choosing the bank profile cannot be done there, because
``detect_profile`` needs text and a scan has none until a page has been through
OCR -- six seconds or so, which does not belong in an HTTP request. So the
worker reads page one, the human confirms what it found, and only then is the
whole document parsed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def now() -> str:
    """UTC, ISO 8601, second precision. Stored as text; compared as text."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobState(str, Enum):
    QUEUED = "QUEUED"            # waiting for a worker
    RUNNING = "RUNNING"          # a worker holds it
    NEEDS_HEADER = "NEEDS_HEADER"  # page 1 read; waiting on a human
    PARSED = "PARSED"            # rows and a chain report exist
    REJECTED = "REJECTED"        # the capture gate refused it
    FAILED = "FAILED"            # the worker raised

    @property
    def terminal(self) -> bool:
        return self in (JobState.PARSED, JobState.REJECTED, JobState.FAILED)


class Stage(str, Enum):
    """What the worker should do when it claims this job."""

    HEADER = "HEADER"  # sample-render, read page 1, detect the profile
    PARSE = "PARSE"    # parse the whole document and settle the chain


class Role(str, Enum):
    """The firm's actual hierarchy, not a generic admin/user split."""

    ARTICLE_CLERK = "ARTICLE_CLERK"
    SENIOR_ACCOUNTANT = "SENIOR_ACCOUNTANT"
    PARTNER = "PARTNER"

    @property
    def rank(self) -> int:
        return {
            "ARTICLE_CLERK": 0,
            "SENIOR_ACCOUNTANT": 1,
            "PARTNER": 2,
        }[self.value]

    def can_act_as(self, required: "Role") -> bool:
        return self.rank >= required.rank


@dataclass(slots=True)
class Principal:
    """Who is asking. Filled by a dev default until step 7 brings sessions."""

    name: str
    role: Role


@dataclass(slots=True)
class Job:
    id: str
    filename: str
    state: JobState
    created_at: str
    updated_at: str
    stage: Stage | None = None
    profile_key: str | None = None

    quality_verdict: str | None = None
    quality: dict[str, Any] | None = None

    account_no: str | None = None
    holder: str | None = None

    #: Money as strings all the way through storage and transport. See
    #: ``store.db`` for why the column is TEXT.
    opening: str | None = None
    closing: str | None = None
    variance: str | None = None

    page_count: int | None = None
    row_count: int | None = None
    unresolved: int | None = None
    reconciled: bool | None = None
    chain: dict[str, Any] | None = None
    #: The rules engine's category summary, or None if the job predates it.
    categories: dict[str, Any] | None = None
    error: str | None = None

    claimed_at: str | None = None
    claimed_by: str | None = None
    progress_done: int = 0
    progress_total: int = 0

    @property
    def blocks_export(self) -> bool:
        """Export needs a paisa-exact tie *and* nothing unresolved.

        A dropped row leaves the endpoints untouched, so arithmetic alone can
        tie while a transaction is missing -- which is the error this whole
        pipeline exists to prevent shipping.
        """
        return not (self.reconciled and not self.unresolved)


@dataclass(slots=True)
class AuditEntry:
    at: str
    actor: str
    role: str
    action: str
    job_id: str | None = None
    detail: str = ""
    reason: str = ""
    id: int | None = None


@dataclass(slots=True)
class Page:
    """One slice of a listing."""

    items: list[Any] = field(default_factory=list)
    total: int = 0
