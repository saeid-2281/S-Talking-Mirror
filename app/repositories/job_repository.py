from __future__ import annotations

from app.database.connection import Database


class JobRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
