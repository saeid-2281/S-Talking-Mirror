from __future__ import annotations

import json
from datetime import datetime, timezone

from app.database.connection import Database
from app.models.persistence import VoiceRecord


class VoiceRepository:
    """Persists provider voice metadata and user favorites."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(
        self,
        *,
        provider: str,
        voice_id: str,
        name: str,
        language: str | None = None,
        category: str | None = None,
        metadata: dict | None = None,
    ) -> VoiceRecord:
        checked_at = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO voices(
                    provider, voice_id, name, language, category,
                    metadata_json, last_checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, voice_id) DO UPDATE SET
                    name = excluded.name,
                    language = excluded.language,
                    category = excluded.category,
                    metadata_json = excluded.metadata_json,
                    last_checked_at = excluded.last_checked_at
                """,
                (
                    provider,
                    voice_id,
                    name,
                    language,
                    category,
                    metadata_json,
                    checked_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM voices WHERE provider = ? AND voice_id = ?",
                (provider, voice_id),
            ).fetchone()
        if row is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Voice upsert did not return a row.")
        return VoiceRecord.from_row(row)

    def get(self, provider: str, voice_id: str) -> VoiceRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM voices WHERE provider = ? AND voice_id = ?",
                (provider, voice_id),
            ).fetchone()
        return VoiceRecord.from_row(row) if row else None

    def list(
        self,
        *,
        provider: str | None = None,
        language: str | None = None,
        favorites_only: bool = False,
    ) -> list[VoiceRecord]:
        clauses: list[str] = []
        parameters: list[object] = []
        if provider:
            clauses.append("provider = ?")
            parameters.append(provider)
        if language:
            clauses.append("language = ?")
            parameters.append(language)
        if favorites_only:
            clauses.append("is_favorite = 1")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM voices{where} ORDER BY id ASC",
                parameters,
            ).fetchall()
        return [VoiceRecord.from_row(row) for row in rows]

    def set_favorite(self, provider: str, voice_id: str, favorite: bool) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE voices SET is_favorite = ? WHERE provider = ? AND voice_id = ?",
                (1 if favorite else 0, provider, voice_id),
            )
