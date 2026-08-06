"""The service layer: upload, the queue, and the worker protocol.

Two things here are worth more than the rest.

The first is that **money never appears as a JSON number**. JSON has no decimal
type, so a figure emitted as a number is handed to the next parser as a float,
and the paisa-exact tie the whole application is built on is lost somewhere no
ordinary assertion would look. The test for it reads the raw response body, not
the parsed object, because by the time it is parsed the evidence is gone.

The second is that the upload request itself grades the capture. That is the
entire promise of the gate -- nobody waits twenty minutes to be told the input
was hopeless -- so it is asserted on the real sixty-page fixture rather than a
toy.
"""

from __future__ import annotations

import pytest

from statementbridge.api.app import create_app
from statementbridge.config import Settings
from statementbridge.store.models import Principal, Role

from .synthpdf import write_image_pdf

TOKEN = "test-worker-token"
WORKER = {"X-Worker-Token": TOKEN}


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        worker_token=TOKEN,
        api_url="http://test",
        worker_concurrency=1,
        claim_timeout=3600,
        reject_blocks_upload=False,
    )


@pytest.fixture()
def client(settings):
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as test_client:
        yield test_client


def upload(client, path, name: str | None = None):
    with path.open("rb") as handle:
        return client.post(
            "/api/v1/jobs",
            files={"file": (name or path.name, handle, "application/pdf")},
        )


# --- the gate runs in the upload request --------------------------------

@pytest.mark.fixtures
def test_uploading_a_bad_scan_reports_the_scanner_setting_immediately(client, gramin_pdf):
    """A 24-page bilevel scan, judged before a single page is rendered."""
    response = upload(client, gramin_pdf)

    assert response.status_code == 201
    body = response.json()
    assert body["job"]["quality_verdict"] == "REJECT"
    assert "greyscale" in body["message"].lower()

    codes = {finding["code"] for finding in body["job"]["quality"]["findings"]}
    assert codes >= {"BILEVEL", "LOW_DPI"}
    # One entry per fault, not one per page: 24 sheets is still one thing to fix.
    assert len(body["job"]["quality"]["findings"]) == len(codes)


@pytest.mark.fixtures
def test_a_rejected_scan_is_still_queued_by_default(client, gramin_pdf):
    """The gate measures; the deployment decides.

    The firm has a backlog already scanned at 150 DPI. A default that made those
    unprocessable would be a worse problem than the one the gate solves, so
    REJECT is advice unless SB_REJECT_BLOCKS_UPLOAD says otherwise.
    """
    body = upload(client, gramin_pdf).json()

    assert body["accepted"] is True
    assert body["job"]["state"] == "QUEUED"


def test_rejection_can_be_made_to_block(tmp_path, settings):
    from fastapi.testclient import TestClient

    settings.reject_blocks_upload = True
    with TestClient(create_app(settings)) as client:
        body = upload(client, write_image_pdf(tmp_path / "fax.pdf", dpi=150, bits=1)).json()

    assert body["accepted"] is False
    assert body["job"]["state"] == "REJECTED"


def test_a_good_scan_is_queued_for_the_header_read(client, tmp_path):
    body = upload(client, write_image_pdf(tmp_path / "good.pdf", dpi=300, bits=8)).json()

    assert body["job"]["quality_verdict"] == "PASS"
    assert body["job"]["state"] == "QUEUED"
    assert body["job"]["stage"] == "HEADER"


def test_only_pdfs_are_accepted(client, tmp_path):
    junk = tmp_path / "statement.xlsx"
    junk.write_bytes(b"not a pdf")

    assert upload(client, junk).status_code == 415


def test_an_unreadable_pdf_is_refused_not_queued(client, tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\nthis is not a pdf body")

    assert upload(client, broken).status_code == 422
    assert client.get("/api/v1/jobs").json()["total"] == 0


# --- money on the wire ---------------------------------------------------

def test_money_is_never_a_json_number(client, tmp_path):
    """Asserted on the raw body: parsing it first would destroy the evidence."""
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(
        f"/internal/jobs/{job_id}/header", json={"profile_key": "gramin_cc"}, headers=WORKER
    )
    client.post(
        f"/api/v1/jobs/{job_id}/header",
        json={"profile_key": "gramin_cc", "opening": "71,85,895.72"},
    )

    raw = client.get(f"/api/v1/jobs/{job_id}").text

    assert '"opening":"-7185895.72"' in raw.replace(" ", "")
    assert '"opening":-7185895.72' not in raw.replace(" ", "")


def test_the_opening_balance_takes_the_sign_of_the_account(client, tmp_path):
    """A cash-credit balance is printed as a magnitude but carried negative.

    Get this wrong and the chain starts from the wrong sign, so every direction
    derived from a delta is inverted -- silently, and on every row.
    """
    def confirm(profile_key: str) -> str:
        job_id = upload(client, write_image_pdf(tmp_path / f"{profile_key}.pdf", dpi=300)).json()["job"]["id"]
        client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
        client.post(
            f"/internal/jobs/{job_id}/header", json={"profile_key": profile_key}, headers=WORKER
        )
        client.post(
            f"/api/v1/jobs/{job_id}/header",
            json={"profile_key": profile_key, "opening": "71,85,895.72"},
        )
        return client.get(f"/api/v1/jobs/{job_id}").json()["opening"]

    assert confirm("gramin_cc") == "-7185895.72"     # cash credit
    assert confirm("sbi_current") == "7185895.72"    # regular current account


# --- the worker protocol -------------------------------------------------

def test_the_queue_needs_the_shared_secret(client):
    assert client.post("/internal/jobs/claim", json={"worker": "w"}).status_code == 401
    assert client.post(
        "/internal/jobs/claim", json={"worker": "w"}, headers={"X-Worker-Token": "wrong"}
    ).status_code == 401


def test_an_empty_queue_answers_no_content(client):
    response = client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)

    assert response.status_code == 204


def test_two_workers_cannot_claim_the_same_job(client, tmp_path):
    upload(client, write_image_pdf(tmp_path / "one.pdf", dpi=300))

    first = client.post("/internal/jobs/claim", json={"worker": "a"}, headers=WORKER)
    second = client.post("/internal/jobs/claim", json={"worker": "b"}, headers=WORKER)

    assert first.status_code == 200
    assert second.status_code == 204


def test_a_job_abandoned_by_a_dead_worker_returns_to_the_queue(client, tmp_path, settings):
    """Otherwise a crashed worker strands its job and the queue stops draining."""
    upload(client, write_image_pdf(tmp_path / "one.pdf", dpi=300))
    claimed = client.post("/internal/jobs/claim", json={"worker": "doomed"}, headers=WORKER)
    assert claimed.status_code == 200

    settings.claim_timeout = -1  # everything in flight is now overdue

    again = client.post("/internal/jobs/claim", json={"worker": "fresh"}, headers=WORKER)
    assert again.status_code == 200
    assert again.json()["id"] == claimed.json()["id"]


def test_the_worker_reports_progress_and_results(client, tmp_path):
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(
        f"/internal/jobs/{job_id}/header", json={"profile_key": "gramin_cc"}, headers=WORKER
    )
    client.post(f"/api/v1/jobs/{job_id}/header", json={"profile_key": "gramin_cc"})
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)

    client.post(
        f"/internal/jobs/{job_id}/progress", json={"done": 7, "total": 24}, headers=WORKER
    )
    assert client.get(f"/api/v1/jobs/{job_id}").json()["progress_done"] == 7

    client.post(
        f"/internal/jobs/{job_id}/result",
        json={
            "rows": [{"narration": "UPI/CR/RAMESH/YBL", "credit": "15400.00"}],
            "chain": {"opening": "0.00"},
            "page_count": 1, "unresolved": 0, "reconciled": True, "variance": "0.00",
        },
        headers=WORKER,
    )

    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["state"] == "PARSED"
    assert job["row_count"] == 1
    assert job["blocks_export"] is False
    assert client.get(f"/api/v1/jobs/{job_id}/rows").json()["total"] == 1


def test_the_confirmed_holder_reaches_the_worker(client, tmp_path):
    """Self-transfer detection is a name match, and the worker has no database.

    So the holder has to travel with the claim, or every transfer between the
    client's own accounts is classified as a payment to a stranger.
    """
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(
        f"/internal/jobs/{job_id}/header", json={"profile_key": "gramin_cc"}, headers=WORKER
    )
    client.post(
        f"/api/v1/jobs/{job_id}/header",
        json={"profile_key": "gramin_cc", "holder": "MR. AJOY NAG"},
    )

    claimed = client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    assert claimed.json()["holder"] == "MR. AJOY NAG"


def test_the_category_summary_survives_the_round_trip(client, tmp_path):
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(
        f"/internal/jobs/{job_id}/header", json={"profile_key": "gramin_cc"}, headers=WORKER
    )
    client.post(f"/api/v1/jobs/{job_id}/header", json={"profile_key": "gramin_cc"})
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)

    summary = {
        "categories": [
            {"code": "T1", "description": "UPI Received (3rd party)", "contra": False,
             "count": 1, "credit": "15400.00", "debit": "0.00"},
        ],
        "count": 1, "total_credit": "15400.00", "total_debit": "0.00",
        "unclassified": 0, "review_count": 0, "contra_count": 0,
        "ledgers": ["Sundry Receipts / Debtors"],
    }
    client.post(
        f"/internal/jobs/{job_id}/result",
        json={
            "rows": [{"narration": "UPI/CR/RAMESH/YBL", "credit": "15400.00",
                      "category": "T1", "tally_ledger": "Sundry Receipts / Debtors"}],
            "chain": {"opening": "0.00"},
            "page_count": 1, "unresolved": 0, "reconciled": True, "variance": "0.00",
            "categories": summary,
        },
        headers=WORKER,
    )

    response = client.get(f"/api/v1/jobs/{job_id}/categories")
    assert response.status_code == 200
    assert response.json() == summary
    assert client.get(f"/api/v1/jobs/{job_id}").json()["categories"]["count"] == 1
    # The per-row decision comes back with the row, needing no route of its own.
    assert client.get(f"/api/v1/jobs/{job_id}/rows").json()["items"][0]["category"] == "T1"


def test_the_summarys_money_is_text_on_the_wire_too(client, tmp_path):
    """Read off the raw body: once it is parsed the evidence is gone."""
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(
        f"/internal/jobs/{job_id}/header", json={"profile_key": "gramin_cc"}, headers=WORKER
    )
    client.post(f"/api/v1/jobs/{job_id}/header", json={"profile_key": "gramin_cc"})
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(
        f"/internal/jobs/{job_id}/result",
        json={
            "rows": [], "chain": {}, "page_count": 1, "unresolved": 0,
            "reconciled": True, "variance": "0.00",
            "categories": {"count": 0, "total_credit": "3240.72",
                           "total_debit": "0.00", "categories": []},
        },
        headers=WORKER,
    )

    body = client.get(f"/api/v1/jobs/{job_id}/categories").text
    assert '"3240.72"' in body
    assert "3240.7199" not in body


def test_categories_are_404_before_the_statement_has_been_parsed(client, tmp_path):
    """A statement nobody has read and one with nothing in it are different."""
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    assert client.get(f"/api/v1/jobs/{job_id}/categories").status_code == 404


def test_a_worker_that_reports_no_categories_still_succeeds(client, tmp_path):
    """The field is optional so an older worker keeps working after an upgrade."""
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(
        f"/internal/jobs/{job_id}/header", json={"profile_key": "gramin_cc"}, headers=WORKER
    )
    client.post(f"/api/v1/jobs/{job_id}/header", json={"profile_key": "gramin_cc"})
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)

    response = client.post(
        f"/internal/jobs/{job_id}/result",
        json={
            "rows": [], "chain": {}, "page_count": 1, "unresolved": 0,
            "reconciled": True, "variance": "0.00",
        },
        headers=WORKER,
    )
    assert response.status_code == 204
    assert client.get(f"/api/v1/jobs/{job_id}").json()["state"] == "PARSED"
    assert client.get(f"/api/v1/jobs/{job_id}/categories").status_code == 404


def test_a_tie_with_unresolved_rows_still_blocks_export(client, tmp_path):
    """Arithmetic alone is not enough, and the API must not imply that it is.

    A row the OCR dropped leaves the endpoints untouched, so the chain can
    balance perfectly while a transaction is missing.
    """
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(
        f"/internal/jobs/{job_id}/header", json={"profile_key": "gramin_cc"}, headers=WORKER
    )
    client.post(f"/api/v1/jobs/{job_id}/header", json={"profile_key": "gramin_cc"})
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(
        f"/internal/jobs/{job_id}/result",
        json={
            "rows": [], "chain": {}, "page_count": 1,
            "unresolved": 3, "reconciled": True, "variance": "0.00",
        },
        headers=WORKER,
    )

    assert client.get(f"/api/v1/jobs/{job_id}").json()["blocks_export"] is True


def test_a_failed_job_keeps_its_error(client, tmp_path):
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(
        f"/internal/jobs/{job_id}/failed", json={"error": "tesseract not found"}, headers=WORKER
    )

    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["state"] == "FAILED"
    assert "tesseract" in job["error"]


# --- the header hand-off -------------------------------------------------

def test_a_header_cannot_be_confirmed_before_it_has_been_read(client, tmp_path):
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]

    response = client.post(f"/api/v1/jobs/{job_id}/header", json={"profile_key": "gramin_cc"})

    assert response.status_code == 409


def test_an_unknown_profile_is_refused_with_the_known_ones(client, tmp_path):
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(f"/internal/jobs/{job_id}/header", json={}, headers=WORKER)

    response = client.post(f"/api/v1/jobs/{job_id}/header", json={"profile_key": "barclays"})

    assert response.status_code == 422
    assert "gramin_cc" in response.json()["detail"]


# --- roles and the audit trail -------------------------------------------

def test_an_override_needs_a_partner(client, tmp_path):
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.app.state.principal = Principal(name="Anita", role=Role.ARTICLE_CLERK)

    refused = client.post(f"/api/v1/jobs/{job_id}/override", json={"reason": "looks fine to me"})
    assert refused.status_code == 403

    client.app.state.principal = Principal(name="Sujata D.", role=Role.PARTNER)
    allowed = client.post(
        f"/api/v1/jobs/{job_id}/override", json={"reason": "client confirmed by phone"}
    )
    assert allowed.status_code == 200


def test_an_override_without_a_reason_is_refused(client, tmp_path):
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]

    assert client.post(f"/api/v1/jobs/{job_id}/override", json={"reason": "ok"}).status_code == 422


def test_every_privileged_action_lands_in_the_audit_trail(client, tmp_path):
    job_id = upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300)).json()["job"]["id"]
    client.post("/internal/jobs/claim", json={"worker": "w"}, headers=WORKER)
    client.post(f"/internal/jobs/{job_id}/header", json={}, headers=WORKER)
    client.post(f"/api/v1/jobs/{job_id}/header", json={"profile_key": "gramin_cc"})
    client.post(f"/api/v1/jobs/{job_id}/override", json={"reason": "client confirmed by phone"})

    trail = client.get(f"/api/v1/jobs/{job_id}/audit").json()

    assert [entry["action"] for entry in trail] == ["UPLOAD", "HEADER_CONFIRMED", "OVERRIDE"]
    assert trail[-1]["reason"] == "client confirmed by phone"


def test_the_audit_trail_cannot_be_edited_or_deleted(client, tmp_path):
    """Enforced by the database, not by the discipline of the code above it.

    Its only value to a partner explaining a figure to a client is that nobody
    could have tidied it afterwards.
    """
    import sqlite3

    upload(client, write_image_pdf(tmp_path / "s.pdf", dpi=300))
    connection = client.app.state.connection

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE audit_log SET reason = 'tidied'")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM audit_log")


# --- the queue screen ----------------------------------------------------

def test_the_queue_lists_and_filters(client, tmp_path):
    upload(client, write_image_pdf(tmp_path / "a.pdf", dpi=300), name="a.pdf")
    upload(client, write_image_pdf(tmp_path / "b.pdf", dpi=150, bits=1), name="b.pdf")

    assert client.get("/api/v1/jobs").json()["total"] == 2
    assert client.get("/api/v1/jobs?state=QUEUED").json()["total"] == 2
    assert client.get("/api/v1/jobs?state=PARSED").json()["total"] == 0


def test_health_reports_the_queue(client, tmp_path):
    upload(client, write_image_pdf(tmp_path / "a.pdf", dpi=300))

    body = client.get("/api/v1/health").json()

    assert body["status"] == "UP"
    assert body["queued"] == 1


def test_an_unknown_job_is_a_404(client):
    assert client.get("/api/v1/jobs/nope").status_code == 404
    assert client.get("/api/v1/jobs/nope/rows").status_code == 404
