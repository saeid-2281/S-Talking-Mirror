from __future__ import annotations

import sqlite3
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.database.migrations import MIGRATIONS, run_migrations


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self._backup_before_pending_migration()
        with self.transaction() as connection:
            run_migrations(connection)

    def _backup_before_pending_migration(self) -> None:
        if not self.path.exists():
            return
        try:
            connection = sqlite3.connect(self.path)
            versions = {
                int(row[0])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            connection.close()
        except sqlite3.Error:
            versions = set()
        for version, _sql in MIGRATIONS:
            if version <= 1 or version in versions:
                continue
            backup = self.path.with_suffix(self.path.suffix + f".pre-v{version}.bak")
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.path, backup)
