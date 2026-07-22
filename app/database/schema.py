from __future__ import annotations

from pathlib import Path

DEFAULT_DATABASE_PATH = Path("data/s_talking.db")

INITIAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    project_file TEXT,
    csv_path TEXT,
    output_path TEXT,
    provider TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    row_number INTEGER NOT NULL,
    filename TEXT NOT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    output_path TEXT,
    duration_seconds REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, row_number)
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    provider TEXT NOT NULL,
    voice_id TEXT,
    model_id TEXT,
    filename TEXT,
    character_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    elapsed_seconds REAL,
    error TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    voice_id TEXT NOT NULL,
    name TEXT NOT NULL,
    language TEXT,
    category TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    is_favorite INTEGER NOT NULL DEFAULT 0,
    last_checked_at TEXT,
    UNIQUE(provider, voice_id)
);

CREATE TABLE IF NOT EXISTS audio_cache (
    cache_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    voice_id TEXT,
    model_id TEXT,
    settings_hash TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_project_status ON jobs(project_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_text_hash ON jobs(text_hash);
CREATE INDEX IF NOT EXISTS idx_history_project_created ON history(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_voices_provider_language ON voices(provider, language);
CREATE INDEX IF NOT EXISTS idx_audio_cache_text_provider ON audio_cache(text_hash, provider);
"""
