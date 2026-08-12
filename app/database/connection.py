from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.database.migrations import MIGRATIONS, run_migrations


class _ClosingConnection(sqlite3.Connection):
    """SQLite connection that closes when used as a context manager.

    ``sqlite3.Connection.__exit__`` only commits or rolls back; it does not
    close the native handle. That behavior leaves database files locked on
    Windows when callers use ``with database.connect()``.
    """

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if os.getenv("S_TALKING_TEST_FAST_PATH", "").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            # Test databases are disposable and do not need power-loss durability.
            # Avoiding fsync-heavy commits removes a large Windows-only cost while
            # preserving SQLite transactions, foreign keys, schema and file I/O.
            connection.execute("PRAGMA synchronous = OFF")
            connection.execute("PRAGMA temp_store = MEMORY")
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

    @property
    def expected_schema_version(self) -> int:
        return max(version for version, _sql in MIGRATIONS)

    def applied_schema_versions(self) -> tuple[int, ...]:
        if not self.path.exists():
            return ()
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        except sqlite3.Error:
            return ()
        finally:
            connection.close()
        return tuple(int(row[0]) for row in rows)

    def quick_check(self, *, full: bool = False) -> str:
        pragma = "integrity_check" if full else "quick_check"
        connection = self.connect()
        try:
            rows = connection.execute(f"PRAGMA {pragma}").fetchall()
        finally:
            connection.close()
        messages = [str(row[0]) for row in rows]
        return "ok" if messages == ["ok"] else "; ".join(messages)

    def foreign_key_violations(self) -> tuple[dict[str, object], ...]:
        connection = self.connect()
        try:
            rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            connection.close()
        return tuple(
            {
                "table": str(row[0]),
                "rowid": row[1],
                "parent": str(row[2]),
                "foreign_key_index": int(row[3]),
            }
            for row in rows
        )

    def backup_to(self, target: Path) -> Path:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        target = Path(target)
        if target.resolve() == self.path.resolve():
            raise ValueError("Backup target must differ from the active database")
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        os.close(handle)
        temp_path = Path(temp_name)
        try:
            source = sqlite3.connect(self.path)
            destination = sqlite3.connect(temp_path)
            try:
                source.execute("PRAGMA wal_checkpoint(PASSIVE)")
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
                source.close()
            if self._database_check(temp_path) != "ok":
                raise sqlite3.DatabaseError("Backup quick_check failed")
            self._replace_file(temp_path, target)
            return target
        finally:
            self._cleanup_temp_file(temp_path)

    def restore_from(self, source_path: Path) -> None:
        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        if self._database_check(source_path) != "ok":
            raise sqlite3.DatabaseError("Source backup quick_check failed")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".restore",
            dir=self.path.parent,
        )
        os.close(handle)
        temp_path = Path(temp_name)
        try:
            source = sqlite3.connect(source_path)
            staged = sqlite3.connect(temp_path)
            try:
                source.backup(staged)
                staged.commit()
            finally:
                staged.close()
                source.close()
            if self._database_check(temp_path) != "ok":
                raise sqlite3.DatabaseError("Restored database quick_check failed")

            # Replacing an active SQLite file is unreliable on Windows because
            # any idle reader can keep the file handle open. SQLite's online
            # backup API writes the staged snapshot into the destination in a
            # transaction and remains safe while other readers are connected.
            staged = sqlite3.connect(temp_path)
            destination = sqlite3.connect(self.path)
            try:
                destination.execute("PRAGMA busy_timeout = 5000")
                staged.backup(destination)
                destination.commit()
            finally:
                destination.close()
                staged.close()
            if self._database_check(self.path) != "ok":
                raise sqlite3.DatabaseError("Active database quick_check failed")
        finally:
            self._cleanup_temp_file(temp_path)

    @staticmethod
    def _database_check(path: Path) -> str:
        # sqlite3 context managers do not close connections; Windows keeps the
        # database file locked until close() runs explicitly.
        connection = sqlite3.connect(path)
        try:
            rows = connection.execute("PRAGMA quick_check").fetchall()
        finally:
            connection.close()
        messages = [str(row[0]) for row in rows]
        return "ok" if messages == ["ok"] else "; ".join(messages)

    @staticmethod
    def _replace_file(source: Path, target: Path) -> None:
        for attempt in range(5):
            try:
                os.replace(source, target)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (2**attempt))

    @classmethod
    def _cleanup_temp_file(cls, path: Path) -> None:
        try:
            cls._unlink_file(path)
        except OSError:
            # Never hide the original backup/restore error with cleanup failure.
            return

    @staticmethod
    def _unlink_file(path: Path) -> None:
        for attempt in range(5):
            try:
                path.unlink(missing_ok=True)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (2**attempt))

    def _backup_before_pending_migration(self) -> None:
        if not self.path.exists():
            return
        versions = set(self.applied_schema_versions())
        for version, _sql in MIGRATIONS:
            if version <= 1 or version in versions:
                continue
            backup = self.path.with_suffix(self.path.suffix + f".pre-v{version}.bak")
            if not backup.exists():
                self.backup_to(backup)
