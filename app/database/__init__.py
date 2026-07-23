from __future__ import annotations

from pathlib import Path

from app.database.connection import Database
from app.database.legacy import JobDatabase
from app.database.schema import DEFAULT_DATABASE_PATH

__all__ = ["DEFAULT_DATABASE_PATH", "Database", "JobDatabase", "initialize_default_database"]


def initialize_default_database(path: Path = DEFAULT_DATABASE_PATH) -> None:
    Database(path).initialize()
