"""The database: SQLite, owned by the API process and nothing else.

The deployment target is a four-bay NAS with no GPU and, once DSM has taken its
share, not much memory to spare. A Postgres container and a Redis container
between them would cost more of that memory than the OCR worker they exist to
coordinate, for one firm posting a few statements an hour. So the queue is a
table, and the only process that opens the file is the API.

That last part is the load-bearing decision. Because the worker never touches
the database -- it claims and reports over HTTP -- it does not have to sit on
the same machine as the file. Moving OCR onto the desktop later is a compose
file and a base URL rather than a migration, which is what keeps the
single-tier recommendation cheap to reverse.

WAL is on because the API writes while a worker reports; transactions are kept
short for the same reason.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: Bumped whenever ``SCHEMA`` changes. Applied on open; there is no downgrade.
#:
#: 2 -- ``jobs.categories_json``, the rules engine's category summary.
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    filename        TEXT NOT NULL,
    state           TEXT NOT NULL,
    stage           TEXT,
    profile_key     TEXT,

    quality_verdict TEXT,
    quality_json    TEXT,

    account_no      TEXT,
    holder          TEXT,

    -- Money is stored as text, never as REAL. SQLite's REAL is a float, and a
    -- float is exactly what this pipeline exists to keep out of the numbers.
    opening         TEXT,
    closing         TEXT,
    variance        TEXT,

    page_count      INTEGER,
    row_count       INTEGER,
    unresolved      INTEGER,
    reconciled      INTEGER,
    chain_json      TEXT,
    categories_json TEXT,
    error           TEXT,

    claimed_at      TEXT,
    claimed_by      TEXT,
    progress_done   INTEGER NOT NULL DEFAULT 0,
    progress_total  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS jobs_queue ON jobs (state, created_at);

CREATE TABLE IF NOT EXISTS job_rows (
    job_id  TEXT NOT NULL,
    idx     INTEGER NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (job_id, idx)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS audit_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,
    actor  TEXT NOT NULL,
    role   TEXT NOT NULL,
    action TEXT NOT NULL,
    job_id TEXT,
    detail TEXT,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS audit_by_job ON audit_log (job_id, id);

-- The audit trail is append-only, and that is enforced here rather than left to
-- the discipline of the code above it. A partner explaining an override to a
-- client needs the record to be one that nobody could have tidied afterwards.
CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


#: Columns added after version 1, as ``(table, column, definition)``.
#:
#: These exist because ``CREATE TABLE IF NOT EXISTS`` does exactly nothing to a
#: table that is already there. Running the schema script over an existing
#: database therefore leaves it on the old shape and reports no error at all --
#: the first sign of trouble is a query failing in production, long after the
#: upgrade looked like it worked. So added columns are applied separately, and
#: by asking the database what it actually has rather than by trusting
#: ``user_version`` to have been written correctly by an earlier release.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("jobs", "categories_json", "TEXT"),
)


def _migrate(connection: sqlite3.Connection) -> list[str]:
    """Bring an existing database up to ``SCHEMA_VERSION``. Idempotent."""
    applied: list[str] = []
    for table, column, definition in _ADDED_COLUMNS:
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if not existing:
            continue  # the table is new; the schema script already built it
        if column not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            applied.append(f"{table}.{column}")
    return applied


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the database, creating and migrating it if necessary."""
    path = Path(path)
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(path), check_same_thread=False, isolation_level=None
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    # A worker reporting a result must not fail because the API happened to be
    # writing; five seconds is far longer than any transaction here takes.
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript(SCHEMA)
    _migrate(connection)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    return connection
