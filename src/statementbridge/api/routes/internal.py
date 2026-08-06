"""The worker protocol.

The worker is an HTTP client and nothing more. It never opens the database, so
it does not have to run on the machine that holds it -- which is what lets OCR
move to the desktop later by changing one environment variable rather than
migrating a schema.

Everything here is gated on a shared secret. That is not user authentication and
does not pretend to be; it stops anything else on the LAN draining the queue.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ...store import jobs
from ...store.models import JobState, Stage
from ..deps import ConnectionDep, SettingsDep, require_worker_token
from ..schemas import (
    ClaimedJob,
    ClaimRequest,
    FailureReport,
    HeaderResult,
    ParseResultIn,
    ProgressReport,
)

router = APIRouter(
    prefix="/internal", tags=["worker"], dependencies=[Depends(require_worker_token)]
)


def _load(connection, job_id: str):
    job = jobs.get(connection, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such job")
    return job


@router.post("/jobs/claim", response_model=ClaimedJob | None)
def claim(
    connection: ConnectionDep,
    settings: SettingsDep,
    request: ClaimRequest,
    response: Response,
) -> ClaimedJob | None:
    """Hand over the next queued job, or answer 204 when there is nothing to do."""
    # A worker that died mid-run would otherwise strand its job in RUNNING for
    # ever and the queue would quietly stop draining.
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.claim_timeout)
    jobs.requeue_stale(connection, before=cutoff.isoformat(timespec="seconds"))

    job = jobs.claim(connection, worker=request.worker)
    if job is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return ClaimedJob(
        id=job.id,
        stage=(job.stage or Stage.HEADER).value,
        source_path=str(settings.upload_path(job.id)),
        profile_key=job.profile_key,
        opening=job.opening,
        closing=job.closing,
    )


@router.post("/jobs/{job_id}/progress", status_code=status.HTTP_204_NO_CONTENT)
def progress(connection: ConnectionDep, job_id: str, report: ProgressReport) -> None:
    _load(connection, job_id)
    jobs.update(
        connection, job_id, progress_done=report.done, progress_total=report.total
    )


@router.post("/jobs/{job_id}/header", status_code=status.HTTP_204_NO_CONTENT)
def header_read(connection: ConnectionDep, job_id: str, result: HeaderResult) -> None:
    """Page one has been read; a human now confirms what it said."""
    _load(connection, job_id)
    fields: dict[str, object] = {
        "state": JobState.NEEDS_HEADER,
        "stage": Stage.PARSE,
        "claimed_at": None,
        "claimed_by": None,
    }
    if result.profile_key:
        fields["profile_key"] = result.profile_key
    if result.account_no:
        fields["account_no"] = result.account_no
    if result.holder:
        fields["holder"] = result.holder
    if result.page_count is not None:
        fields["page_count"] = result.page_count
    if result.quality is not None:
        # The sampled render adds skew and contrast to what the structural
        # stage already found at upload.
        fields["quality_json"] = result.quality.model_dump()
        fields["quality_verdict"] = result.quality.verdict
    jobs.update(connection, job_id, **fields)


@router.post("/jobs/{job_id}/result", status_code=status.HTTP_204_NO_CONTENT)
def parsed(connection: ConnectionDep, job_id: str, result: ParseResultIn) -> None:
    _load(connection, job_id)
    jobs.save_rows(connection, job_id, result.rows)
    jobs.update(
        connection, job_id,
        state=JobState.PARSED, stage=None,
        page_count=result.page_count, row_count=len(result.rows),
        unresolved=result.unresolved, reconciled=result.reconciled,
        variance=result.variance, chain_json=result.chain,
        claimed_at=None, claimed_by=None, error=None,
    )


@router.post("/jobs/{job_id}/failed", status_code=status.HTTP_204_NO_CONTENT)
def failed(connection: ConnectionDep, job_id: str, report: FailureReport) -> None:
    _load(connection, job_id)
    jobs.update(
        connection, job_id,
        state=JobState.FAILED, error=report.error,
        claimed_at=None, claimed_by=None,
    )
