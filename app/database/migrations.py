from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone

from app.database.schema import INITIAL_SCHEMA_SQL

Migration = tuple[int, str]
MIGRATIONS: Sequence[Migration] = ((1, INITIAL_SCHEMA_SQL),)


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
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)",
            (version, utc_now()),
        )
