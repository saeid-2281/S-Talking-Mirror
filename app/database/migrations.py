from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone

from app.database.schema import INITIAL_SCHEMA_SQL

Migration = tuple[int, str]
MULTI_SOURCE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS project_sources (
    source_id TEXT PRIMARY KEY,
    project_id INTEGER,
    display_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_path TEXT NOT NULL,
    worksheet_name TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    import_order INTEGER NOT NULL DEFAULT 0,
    detected_encoding TEXT,
    detected_delimiter TEXT,
    text_column TEXT NOT NULL DEFAULT 'text',
    filename_column TEXT NOT NULL DEFAULT 'filename',
    voice_column TEXT,
    model_column TEXT,
    language_column TEXT,
    output_subfolder_column TEXT,
    row_start INTEGER NOT NULL DEFAULT 2,
    row_end INTEGER,
    imported_at TEXT,
    last_modified TEXT,
    source_hash TEXT,
    import_status TEXT NOT NULL DEFAULT 'ready',
    valid_rows INTEGER NOT NULL DEFAULT 0,
    rejected_rows INTEGER NOT NULL DEFAULT 0,
    issue_count INTEGER NOT NULL DEFAULT 0,
    settings_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS source_worksheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    worksheet_name TEXT NOT NULL,
    worksheet_order INTEGER NOT NULL DEFAULT 0,
    selected INTEGER NOT NULL DEFAULT 1,
    header_json TEXT NOT NULL DEFAULT '[]',
    preview_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY(source_id) REFERENCES project_sources(source_id) ON DELETE CASCADE,
    UNIQUE(source_id, worksheet_name)
);

CREATE TABLE IF NOT EXISTS source_import_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_hash TEXT,
    FOREIGN KEY(source_id) REFERENCES project_sources(source_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS provider_profiles (
    profile_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    display_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 0,
    safe_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    job_id INTEGER,
    provider TEXT NOT NULL,
    profile_id TEXT,
    request_id TEXT,
    usage_amount REAL,
    usage_unit TEXT,
    estimated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
);

ALTER TABLE jobs ADD COLUMN source_id TEXT;
ALTER TABLE jobs ADD COLUMN source_display_name TEXT;
ALTER TABLE jobs ADD COLUMN source_sheet TEXT;
ALTER TABLE jobs ADD COLUMN source_row INTEGER;
ALTER TABLE jobs ADD COLUMN provider_override TEXT;
ALTER TABLE jobs ADD COLUMN account_profile_override TEXT;
ALTER TABLE jobs ADD COLUMN voice_override TEXT;
ALTER TABLE jobs ADD COLUMN model_override TEXT;
ALTER TABLE jobs ADD COLUMN language_override TEXT;
ALTER TABLE jobs ADD COLUMN output_subfolder TEXT;

CREATE INDEX IF NOT EXISTS idx_project_sources_project_order ON project_sources(project_id, import_order);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(project_id, source_id);
CREATE INDEX IF NOT EXISTS idx_provider_usage_project ON provider_usage(project_id, provider, created_at);
"""

MIGRATIONS: Sequence[Migration] = ((1, INITIAL_SCHEMA_SQL), (2, MULTI_SOURCE_SCHEMA_SQL))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migration_statements(sql: str) -> list[str]:
    statements: list[str] = []
    pending = ""
    for line in sql.splitlines():
        pending = f"{pending}\n{line}".strip()
        if sqlite3.complete_statement(pending):
            statements.append(pending.rstrip(";").strip())
            pending = ""
    if pending.strip():
        statements.append(pending.strip())
    return statements


def run_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {
        int(row["version"])
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, sql in sorted(MIGRATIONS, key=lambda item: item[0]):
        if version in applied:
            continue
        for statement in migration_statements(sql):
            try:
                connection.execute(statement)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)",
            (version, utc_now()),
        )
