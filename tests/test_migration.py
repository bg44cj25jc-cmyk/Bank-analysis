"""Opening a database written by an older release.

This is tested rather than inspected because of how the failure looks. SQLite's
``CREATE TABLE IF NOT EXISTS`` does not compare the table it finds against the
one it was asked for -- it sees a table of that name and stops. So a release
that adds a column and relies on the schema script alone leaves every existing
database on the old shape, reports nothing, starts cleanly, and serves requests
until the first query that touches the new column. On a machine holding one
firm's year of statements, that is a long way past the point of noticing.
"""

from __future__ import annotations

import json
import sqlite3

from statementbridge.store import jobs
from statementbridge.store.db import SCHEMA_VERSION, connect
from statementbridge.store.models import JobState, Stage

#: The v1 ``jobs`` table exactly as it shipped: no ``categories_json``.
V1_SCHEMA = """
CREATE TABLE jobs (
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
    opening         TEXT,
    closing         TEXT,
    variance        TEXT,
    page_count      INTEGER,
    row_count       INTEGER,
    unresolved      INTEGER,
    reconciled      INTEGER,
    chain_json      TEXT,
    error           TEXT,
    claimed_at      TEXT,
    claimed_by      TEXT,
    progress_done   INTEGER NOT NULL DEFAULT 0,
    progress_total  INTEGER NOT NULL DEFAULT 0
);
"""


def write_v1_database(path, *, job_id: str = "old-job") -> None:
    connection = sqlite3.connect(str(path))
    connection.executescript(V1_SCHEMA)
    connection.execute(
        "INSERT INTO jobs (id, created_at, updated_at, filename, state, stage, "
        "holder, chain_json) VALUES (?,?,?,?,?,?,?,?)",
        (
            job_id, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
            "statement.pdf", JobState.PARSED.value, None, "MR. AJOY NAG",
            json.dumps({"opening": "131.24"}),
        ),
    )
    connection.execute("PRAGMA user_version=1")
    connection.commit()
    connection.close()


def columns_of(connection, table: str) -> set[str]:
    return {
        row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
    }


def test_an_existing_database_gains_the_new_column(tmp_path):
    path = tmp_path / "statementbridge.sqlite"
    write_v1_database(path)

    connection = connect(path)
    assert "categories_json" in columns_of(connection, "jobs")
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_the_jobs_already_in_it_survive_untouched(tmp_path):
    """A migration that lost a year of statements would be the worse failure."""
    path = tmp_path / "statementbridge.sqlite"
    write_v1_database(path)

    connection = connect(path)
    job = jobs.get(connection, "old-job")
    assert job is not None
    assert job.filename == "statement.pdf"
    assert job.holder == "MR. AJOY NAG"
    assert job.state is JobState.PARSED
    assert job.chain == {"opening": "131.24"}
    # Parsed before the rules engine existed: no categories, and that is not
    # the same as a statement in which nothing matched.
    assert job.categories is None


def test_opening_it_twice_changes_nothing(tmp_path):
    """Migration runs on every open, so it has to be safe on every open."""
    path = tmp_path / "statementbridge.sqlite"
    write_v1_database(path)

    connect(path).close()
    connection = connect(path)
    assert "categories_json" in columns_of(connection, "jobs")
    assert jobs.get(connection, "old-job") is not None


def test_a_migrated_database_takes_a_summary_like_any_other(tmp_path):
    path = tmp_path / "statementbridge.sqlite"
    write_v1_database(path)
    connection = connect(path)

    jobs.update(connection, "old-job", categories_json={"count": 236})
    assert jobs.get(connection, "old-job").categories == {"count": 236}


def test_a_fresh_database_needs_no_migration_to_have_the_column(tmp_path):
    connection = connect(tmp_path / "new.sqlite")
    assert "categories_json" in columns_of(connection, "jobs")

    job = jobs.create(
        connection, filename="s.pdf", state=JobState.QUEUED, stage=Stage.HEADER,
        quality_verdict="ACCEPT", quality={},
    )
    assert job.categories is None
