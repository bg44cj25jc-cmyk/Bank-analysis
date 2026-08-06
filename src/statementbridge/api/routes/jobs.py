"""The routes people use.

Upload is where the capture gate earns its keep: the structural stage runs
inside this request, costs about a third of a second on a sixty-page file, and
tells whoever dropped the PDF what is wrong with it and which scanner setting
to change -- rather than letting them find out twenty minutes into a job that
could never have reconciled.

Upload and export are desktop-only by design; the mobile tier reviews and
corrects. There is deliberately no mobile upload route to build against.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from ...ingest.quality import DocumentQuality, Verdict, inspect
from ...money import parse_amount, signed_from_drcr
from ...parse.profiles import gramin_cc, sbi_current  # noqa: F401  (registers profiles)
from ...parse.profiles.base import all_profiles, get_profile
from ...store import audit, jobs
from ...store.models import JobState, Role, Stage
from ..deps import ConnectionDep, PrincipalDep, SettingsDep, require_role
from ..schemas import (
    AuditEntryOut,
    HeaderConfirmation,
    JobDetail,
    JobList,
    JobSummary,
    OverrideRequest,
    QualityFinding,
    QualityReport,
    RowPage,
    UploadResponse,
)

router = APIRouter(prefix="/api/v1", tags=["jobs"])


def quality_out(report: DocumentQuality) -> QualityReport:
    return QualityReport(
        verdict=report.verdict.value,
        summary=report.summary,
        effective_dpi=report.effective_dpi,
        pages=len(report.pages),
        scanned_pages=len(report.scanned_pages),
        mixed=report.mixed,
        findings=[
            QualityFinding(
                code=finding.code,
                verdict=finding.verdict.value,
                detail=finding.detail,
                remedy=finding.remedy,
            )
            # One entry per distinct fault, not one per page: a 60-page scan at
            # the wrong resolution is one thing to fix, not sixty.
            for finding in {
                finding.code: finding
                for page in report.pages
                for finding in page.findings
            }.values()
        ],
    )


def summary_out(job) -> JobSummary:
    return JobSummary(
        id=job.id, filename=job.filename, state=job.state.value,
        stage=job.stage.value if job.stage else None,
        created_at=job.created_at, updated_at=job.updated_at,
        profile_key=job.profile_key, quality_verdict=job.quality_verdict,
        account_no=job.account_no, holder=job.holder,
        page_count=job.page_count, row_count=job.row_count,
        unresolved=job.unresolved, reconciled=job.reconciled,
        opening=job.opening, closing=job.closing, variance=job.variance,
        progress_done=job.progress_done,
        progress_total=job.progress_total, error=job.error,
    )


def detail_out(job) -> JobDetail:
    return JobDetail(
        **summary_out(job).model_dump(),
        quality=QualityReport(**job.quality) if job.quality else None,
        chain=job.chain,
        blocks_export=job.blocks_export,
    )


def _load(connection, job_id: str):
    job = jobs.get(connection, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such job")
    return job


@router.post("/jobs", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload(
    connection: ConnectionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    file: Annotated[UploadFile, File()],
) -> UploadResponse:
    """Take a statement, grade its capture, and queue it if it is worth parsing."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only PDF statements are accepted"
        )

    staged = settings.scratch_dir / "incoming"
    staged.mkdir(parents=True, exist_ok=True)
    temporary = staged / f"{file.filename}"
    with temporary.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    # Structural checks only: no rendering, so no Poppler and no waiting. The
    # sampled render happens on the worker, where seconds are affordable.
    try:
        report = inspect(temporary, render_sample=False)
    except Exception as error:
        temporary.unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"could not read the PDF: {error}"
        ) from error

    rejected = report.verdict is Verdict.REJECT
    blocked = rejected and settings.reject_blocks_upload

    job = jobs.create(
        connection,
        filename=file.filename or "statement.pdf",
        state=JobState.REJECTED if blocked else JobState.QUEUED,
        stage=None if blocked else Stage.HEADER,
        quality_verdict=report.verdict.value,
        quality=quality_out(report).model_dump(),
    )

    destination = settings.upload_path(job.id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(temporary), destination)

    audit.record(
        connection, principal, "UPLOAD", job_id=job.id,
        detail=f"{file.filename} — {report.verdict.value}: {report.summary}",
    )

    return UploadResponse(
        job=detail_out(_load(connection, job.id)),
        accepted=not blocked,
        message=report.summary,
    )


@router.get("/jobs", response_model=JobList)
def queue(
    connection: ConnectionDep,
    state: Annotated[JobState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobList:
    found, total = jobs.listing(connection, state=state, limit=limit, offset=offset)
    return JobList(items=[summary_out(job) for job in found], total=total)


@router.get("/jobs/{job_id}", response_model=JobDetail)
def detail(connection: ConnectionDep, job_id: str) -> JobDetail:
    return detail_out(_load(connection, job_id))


@router.post("/jobs/{job_id}/header", response_model=JobDetail)
def confirm_header(
    connection: ConnectionDep,
    principal: PrincipalDep,
    job_id: str,
    confirmation: HeaderConfirmation,
) -> JobDetail:
    """Accept the account header a human checked, and queue the full parse.

    The control totals arrive as printed -- ``"71,85,895.72"`` -- and are parsed
    with the same reader the statement pages go through, never with ``float()``.
    """
    job = _load(connection, job_id)
    if job.state is not JobState.NEEDS_HEADER:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"job is {job.state.value}, not awaiting a header",
        )
    try:
        profile = get_profile(confirmation.profile_key)
    except KeyError:
        known = ", ".join(sorted(name.key for name in all_profiles()))
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unknown profile {confirmation.profile_key!r}; known: {known}",
        ) from None

    def money(raw: str | None) -> str | None:
        """Read a printed figure into the signed convention the pipeline uses.

        The control totals are typed as they appear on the statement, which is
        a magnitude with no sign. On a cash-credit or overdraft account that
        printed figure is a *debit*, and the pipeline carries debits negative --
        so the same conversion the CLI applies has to happen here too, or the
        chain starts from a balance of the wrong sign and every direction
        derived from it is inverted.
        """
        if not raw:
            return None
        parsed = parse_amount(raw)
        if parsed.value is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"cannot read the figure {raw!r}"
            )
        marker = parsed.sign_hint or ("DR" if profile.is_overdraft else "CR")
        return str(signed_from_drcr(parsed.value, marker))

    updated = jobs.update(
        connection, job_id,
        state=JobState.QUEUED, stage=Stage.PARSE,
        profile_key=confirmation.profile_key,
        account_no=confirmation.account_no, holder=confirmation.holder,
        opening=money(confirmation.opening), closing=money(confirmation.closing),
    )
    audit.record(
        connection, principal, "HEADER_CONFIRMED", job_id=job_id,
        detail=f"profile={confirmation.profile_key} account={confirmation.account_no}",
    )
    return detail_out(updated)


@router.get("/jobs/{job_id}/rows", response_model=RowPage)
def extracted_rows(
    connection: ConnectionDep,
    job_id: str,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RowPage:
    _load(connection, job_id)
    items, total = jobs.rows(connection, job_id, limit=limit, offset=offset)
    return RowPage(items=items, total=total)


@router.get("/jobs/{job_id}/audit", response_model=list[AuditEntryOut])
def job_audit(connection: ConnectionDep, job_id: str) -> list[AuditEntryOut]:
    _load(connection, job_id)
    return [
        AuditEntryOut(**asdict(entry)) for entry in audit.for_job(connection, job_id)
    ]


@router.post("/jobs/{job_id}/override", response_model=JobDetail)
def override(
    connection: ConnectionDep,
    job_id: str,
    request: OverrideRequest,
    principal: Annotated[object, Depends(require_role(Role.PARTNER))],
) -> JobDetail:
    """Let a partner push a blocked job forward, on the record.

    The reason is required and is written to a table that cannot be edited or
    deleted, because its only value is to a partner explaining the figure to a
    client afterwards.
    """
    job = _load(connection, job_id)
    audit.record(
        connection, principal, "OVERRIDE", job_id=job_id,
        detail=f"state={job.state.value} verdict={job.quality_verdict} "
               f"variance={job.variance} unresolved={job.unresolved}",
        reason=request.reason,
    )
    if job.state is JobState.REJECTED:
        job = jobs.update(connection, job_id, state=JobState.QUEUED, stage=Stage.HEADER)
    return detail_out(job)
