"""The worker: claim a job, do the slow part, report back.

This is the only process that needs Tesseract, Poppler and OpenCV, and the only
one that will saturate a core for minutes at a time. Keeping it behind an HTTP
boundary is what lets the deployment start as one machine and become two without
being rewritten -- and what lets the API keep answering the review screens while
a sixty-page statement is being recognised.

It polls rather than being pushed to. At a few statements an hour a poll every
couple of seconds costs nothing measurable, and it means a worker that was off,
restarted, or newly pointed at a different API simply picks up where the queue
is -- no broker, no subscriptions, no state of its own to lose.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import time
import traceback
from decimal import Decimal
from pathlib import Path

from ..balance.repair import settle
from ..config import Settings, load
from ..parse import route
from ..parse.profiles import gramin_cc, sbi_current  # noqa: F401  (registers profiles)
from ..parse.profiles.base import get_profile
from ..rules.engine import classify, movements
from ..rules.summary import summarise
from ..store.jobs import record_of
from . import header
from .client import ApiClient, ClaimedJob

log = logging.getLogger("statementbridge.worker")

#: How long to wait after finding the queue empty.
IDLE_SLEEP = 2.0
#: How long to wait after an error reaching the API, so a restarting API is not
#: hammered while it comes up.
ERROR_SLEEP = 10.0


class Worker:
    def __init__(self, client: ApiClient, name: str) -> None:
        self.client = client
        self.name = name
        self.running = True

    def stop(self, *_: object) -> None:
        # Finish the job in hand; do not abandon a half-recognised document.
        log.info("stop requested; finishing the current job first")
        self.running = False

    def run_once(self) -> bool:
        """Claim and process one job. True if there was work to do."""
        job = self.client.claim(self.name)
        if job is None:
            return False

        log.info("claimed %s (%s)", job.id[:8], job.stage)
        started = time.perf_counter()
        try:
            if job.stage == "HEADER":
                self.read_header(job)
            else:
                self.parse(job)
            log.info("finished %s in %.1fs", job.id[:8], time.perf_counter() - started)
        except Exception:
            detail = traceback.format_exc()
            log.error("job %s failed\n%s", job.id[:8], detail)
            self.client.failed(job.id, detail)
        return True

    def read_header(self, job: ClaimedJob) -> None:
        """Grade the capture fully and propose the account header."""
        findings = header.read(Path(job.source_path), profile_key=job.profile_key)
        payload: dict[str, object] = {
            "profile_key": findings.profile_key,
            "account_no": findings.account_no,
            "holder": findings.holder,
            "page_count": findings.page_count,
        }
        if findings.quality is not None:
            from ..api.routes.jobs import quality_out

            payload["quality"] = quality_out(findings.quality).model_dump()
        self.client.header(job.id, payload)

    def parse(self, job: ClaimedJob) -> None:
        """The slow one: recognise the whole document and settle the chain."""
        if not job.profile_key:
            raise RuntimeError("cannot parse without a confirmed bank profile")
        profile = get_profile(job.profile_key)

        def progress(done: int, total: int) -> None:
            self.client.progress(job.id, done, total)

        result = route.parse_statement(
            Path(job.source_path), profile, progress=progress
        )

        # Control totals were stored already signed, so they are read straight
        # back as Decimals -- no float anywhere on this path.
        opening = Decimal(job.opening) if job.opening else Decimal("0.00")
        closing = Decimal(job.closing) if job.closing else None
        chain, _ = settle(result.rows, opening, closing=closing)

        # Classification runs here because this is where the rows are, and it
        # costs nothing next to the OCR that produced them. The holder came
        # down with the job: self-transfer detection is a name match, and there
        # is no database on this side to look the name up in.
        decisions = classify(result.rows, holder=job.holder)
        for row, decision in zip(result.rows, decisions):
            row.apply(decision)
        categories = summarise(movements(result.rows, decisions))

        self.client.result(
            job.id,
            {
                "rows": [record_of(row) for row in result.rows],
                "categories": categories.as_dict(),
                "chain": {
                    "opening": str(chain.opening),
                    "closing_computed": str(chain.closing_computed),
                    "closing_printed": (
                        str(chain.closing_printed)
                        if chain.closing_printed is not None
                        else None
                    ),
                    "total_debit": str(chain.total_debit),
                    "total_credit": str(chain.total_credit),
                    "debit_count": chain.debit_count,
                    "credit_count": chain.credit_count,
                    "repaired": chain.repaired,
                    "unresolved": chain.unresolved,
                    "balances_tie": chain.balances_tie,
                    "notes": chain.notes,
                },
                "page_count": result.page_count,
                "unresolved": chain.unresolved,
                "reconciled": chain.reconciled,
                "variance": str(chain.variance),
            },
        )

    def serve(self) -> None:
        log.info("worker %s polling %s", self.name, self.client._client.base_url)
        while self.running:
            try:
                if not self.run_once():
                    time.sleep(IDLE_SLEEP)
            except Exception as error:
                # Reaching the API failed, not the job. Back off and retry:
                # the API may simply be restarting.
                log.warning("cannot reach the API (%s); retrying", error)
                time.sleep(ERROR_SLEEP)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="statementbridge-worker",
        description="Pull OCR and parsing jobs from a StatementBridge API.",
    )
    parser.add_argument("--api-url", default=None, help="overrides SB_API_URL")
    parser.add_argument("--name", default=None, help="worker name in the audit trail")
    parser.add_argument("--once", action="store_true", help="process one job and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )
    settings: Settings = load()
    base_url = args.api_url or settings.api_url
    name = args.name or f"{socket.gethostname()}-{os.getpid()}"

    with ApiClient(base_url, settings.worker_token) as client:
        worker = Worker(client, name)
        signal.signal(signal.SIGTERM, worker.stop)
        signal.signal(signal.SIGINT, worker.stop)
        if args.once:
            return 0 if worker.run_once() else 1
        worker.serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
