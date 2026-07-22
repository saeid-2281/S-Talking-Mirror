from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectRecord:
    id: int
    name: str
    project_file: str | None
    csv_path: str | None
    output_path: str | None
    provider: str
    settings_json: str
    created_at: str
    updated_at: str
    last_opened_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ProjectRecord":
        return cls(**dict(row))


@dataclass(frozen=True)
class JobRecord:
    id: int
    project_id: int
    row_number: int
    filename: str
    text: str
    text_hash: str
    status: str
    retry_count: int
    error: str | None
    output_path: str | None
    duration_seconds: float | None
    created_at: str
    updated_at: str
    completed_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "JobRecord":
        return cls(**dict(row))


@dataclass(frozen=True)
class HistoryRecord:
    id: int
    project_id: int | None
    provider: str
    voice_id: str | None
    model_id: str | None
    filename: str | None
    character_count: int
    status: str
    elapsed_seconds: float | None
    error: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "HistoryRecord":
        return cls(**dict(row))


@dataclass(frozen=True)
class VoiceRecord:
    id: int
    provider: str
    voice_id: str
    name: str
    language: str | None
    category: str | None
    metadata_json: str
    is_favorite: int
    last_checked_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "VoiceRecord":
        return cls(**dict(row))


@dataclass(frozen=True)
class CacheRecord:
    cache_key: str
    provider: str
    voice_id: str | None
    model_id: str | None
    settings_hash: str
    text_hash: str
    file_path: str
    file_size: int | None
    created_at: str
    last_used_at: str
    hit_count: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "CacheRecord":
        return cls(**dict(row))
