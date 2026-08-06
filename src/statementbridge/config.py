"""Deployment settings, all of them environment variables with sane defaults.

Everything the two tiers disagree about lives here. In particular
``SB_API_URL``: the worker reaches the API through it, and on a single-machine
deployment that is just the sibling container. Pointing it at the desktop is how
OCR moves off the NAS later without a line of code changing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(slots=True)
class Settings:
    #: Root of everything written at runtime. On the NAS the database and
    #: scratch belong on the NVMe pool and uploads on the encrypted share; the
    #: compose file mounts them accordingly.
    data_dir: Path

    #: Shared secret on the worker protocol. Not a substitute for the app
    #: authentication that arrives with roles -- it only stops anything on the
    #: LAN claiming jobs off the queue.
    worker_token: str

    #: Where the worker finds the API.
    api_url: str

    #: Concurrent OCR workers per host. Two leaves cores for the API and DSM;
    #: each one peaks around a gigabyte, which is the binding constraint.
    worker_concurrency: int

    #: Seconds a RUNNING job may sit untouched before it is assumed abandoned.
    claim_timeout: int

    #: Whether a REJECT verdict blocks the upload outright.
    #:
    #: The gate measures; this decides. It is a setting because the firm has a
    #: backlog of statements already scanned at 150 DPI, and a deployment that
    #: made those unprocessable would be a worse problem than the one the gate
    #: solves.
    reject_blocks_upload: bool

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db" / "statementbridge.sqlite"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def scratch_dir(self) -> Path:
        return self.data_dir / "scratch"

    def upload_path(self, job_id: str) -> Path:
        return self.uploads_dir / job_id / "source.pdf"


def load() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get("SB_DATA_DIR", "./data")),
        worker_token=os.environ.get("SB_WORKER_TOKEN", "dev-worker-token"),
        api_url=os.environ.get("SB_API_URL", "http://localhost:8000"),
        worker_concurrency=int(os.environ.get("SB_WORKER_CONCURRENCY", "2")),
        claim_timeout=int(os.environ.get("SB_CLAIM_TIMEOUT", "3600")),
        reject_blocks_upload=_flag("SB_REJECT_BLOCKS_UPLOAD", False),
    )
