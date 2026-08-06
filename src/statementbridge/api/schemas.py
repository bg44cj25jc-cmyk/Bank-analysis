"""Request and response shapes.

One rule governs all of them: **money is a string on the wire, never a JSON
number.** JSON has no decimal type, so a figure emitted as a number is handed to
the next parser as a float, and the paisa-exact tie this application is built
around is lost somewhere no test would look. The client's own workbook carries
``3240.71999999997`` and a ``-2.77e-11`` variance from exactly that mistake.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QualityFinding(BaseModel):
    code: str
    verdict: str
    detail: str
    remedy: str = ""


class QualityReport(BaseModel):
    verdict: str
    summary: str
    effective_dpi: float | None = None
    pages: int = 0
    scanned_pages: int = 0
    mixed: bool = False
    findings: list[QualityFinding] = Field(default_factory=list)


class JobSummary(BaseModel):
    """The queue row."""

    id: str
    filename: str
    state: str
    stage: str | None = None
    created_at: str
    updated_at: str
    profile_key: str | None = None
    quality_verdict: str | None = None
    account_no: str | None = None
    holder: str | None = None
    page_count: int | None = None
    row_count: int | None = None
    unresolved: int | None = None
    reconciled: bool | None = None
    #: Decimals as text, all three. See the module docstring.
    opening: str | None = None
    closing: str | None = None
    variance: str | None = None
    progress_done: int = 0
    progress_total: int = 0
    error: str | None = None


class JobDetail(JobSummary):
    quality: QualityReport | None = None
    chain: dict[str, Any] | None = None
    #: The category summary. Its money is text, like everything else here.
    categories: dict[str, Any] | None = None
    blocks_export: bool = True


class JobList(BaseModel):
    items: list[JobSummary]
    total: int


class UploadResponse(BaseModel):
    job: JobDetail
    accepted: bool
    message: str


class HeaderConfirmation(BaseModel):
    """What the desktop sends back from the confirm-header screen."""

    profile_key: str
    account_no: str | None = None
    holder: str | None = None
    #: Control totals as printed, e.g. ``"71,85,895.72"``. Parsed with
    #: ``money.parse_amount``, never with ``float()``.
    opening: str | None = None
    closing: str | None = None


class OverrideRequest(BaseModel):
    reason: str = Field(min_length=8)


class RowPage(BaseModel):
    items: list[dict[str, Any]]
    total: int


class AuditEntryOut(BaseModel):
    id: int | None = None
    at: str
    actor: str
    role: str
    action: str
    job_id: str | None = None
    detail: str = ""
    reason: str = ""


# --- the worker protocol -------------------------------------------------


class ClaimRequest(BaseModel):
    worker: str


class ClaimedJob(BaseModel):
    """Everything the worker needs; it never reads the database itself."""

    id: str
    stage: str
    source_path: str
    profile_key: str | None = None
    opening: str | None = None
    closing: str | None = None
    #: The confirmed account holder. The worker classifies, and self-transfer
    #: detection is a name match, so the name has to travel with the job --
    #: there is no database on that side to look it up in.
    holder: str | None = None


class ProgressReport(BaseModel):
    done: int
    total: int


class HeaderResult(BaseModel):
    """What reading page one turned up."""

    profile_key: str | None = None
    account_no: str | None = None
    holder: str | None = None
    page_count: int | None = None
    quality: QualityReport | None = None


class ParseResultIn(BaseModel):
    rows: list[dict[str, Any]]
    chain: dict[str, Any]
    page_count: int
    unresolved: int
    reconciled: bool
    variance: str
    #: Optional so a worker built before the rules engine still reports
    #: successfully. Its rows simply arrive uncategorised.
    categories: dict[str, Any] | None = None


class FailureReport(BaseModel):
    error: str
