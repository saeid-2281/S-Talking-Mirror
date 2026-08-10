from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.retry_policy import FailureCategory, RetryHistoryEntry


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class AppSettings(BaseModel):
    provider: str = "elevenlabs"
    api_key: str = ""
    voice_id: str = ""
    model_id: str = "eleven_multilingual_v2"
    language_code: str | None = "da"
    output_format: str = "mp3_44100_128"
    file_extension: str = ".mp3"

    stability: float = Field(default=0.45, ge=0.0, le=1.0)
    similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0)
    style: float = Field(default=0.2, ge=0.0, le=1.0)
    use_speaker_boost: bool = True
    speed: float = Field(default=1.0, ge=0.7, le=1.2)
    short_text_pronunciation_aid: bool = True
    pronunciation_dictionary_locators: list[dict[str, Any]] = Field(default_factory=list)
    active_pronunciation_dictionary_id: str | None = None
    job_pronunciation_overrides: dict[int, str] = Field(default_factory=dict)
    active_api_profile_id: str | None = None
    provider_options: dict[str, Any] = Field(default_factory=dict)
    api_profile_failover: str = "never"
    api_profile_failover_max_switches: int = Field(default=1, ge=0, le=20)
    api_profile_failover_sequence_mode: str = "active_then_backups"
    api_profile_failover_manual_sequence: list[str] = Field(default_factory=list)
    allow_unknown_quota_override: bool = False
    generation_scope: str = "entire_queue"
    execution_order: str = "csv"

    delay_seconds: float = Field(default=0.5, ge=0.0, le=60.0)
    timeout_seconds: float = Field(default=90.0, ge=5.0, le=600.0)
    max_retries: int = Field(default=4, ge=0, le=10)

    skip_existing: bool = True
    overwrite_existing: bool = False
    piper_model_path: str | None = None

    @field_validator("file_extension")
    @classmethod
    def normalize_extension(cls, value: str) -> str:
        value = value.strip()
        return value if value.startswith(".") else f".{value}"

    @model_validator(mode="after")
    def validate_file_policy(self) -> "AppSettings":
        if self.skip_existing and self.overwrite_existing:
            raise ValueError("skip_existing and overwrite_existing cannot both be true")
        return self


class TTSJob(BaseModel):
    row_number: int
    text: str
    filename: str
    source_physical_row: int | None = None
    import_status: str = "imported"
    import_issue_code: str | None = None
    status: JobStatus = JobStatus.PENDING
    error: str | None = None
    retry_count: int = 0
    failure_category: FailureCategory | None = None
    error_code: str | None = None
    error_fingerprint: str | None = None
    retryable: bool | None = None
    retry_exhausted: bool = False
    next_retry_at: str | None = None
    retry_history: list[RetryHistoryEntry] = Field(default_factory=list)
    duration_seconds: float = 0.0
    generated_output_path: str | None = None
    pronunciation_override: str | None = None
    source_id: str | None = None
    source_display_name: str | None = None
    source_sheet: str | None = None
    source_row: int | None = None
    voice_override: str | None = None
    model_override: str | None = None
    language_override: str | None = None
    provider_override: str | None = None
    account_profile_override: str | None = None
    output_subfolder: str | None = None
    original_order: int | None = None
    custom_order: int | None = None

    @property
    def character_count(self) -> int:
        return len(self.text)

    @field_validator("text", "filename")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    def output_path(self, output_dir: Path, extension: str) -> Path:
        safe_name = Path(self.filename).name
        path = Path(safe_name)
        if not path.suffix:
            path = path.with_suffix(extension)
        if self.output_subfolder:
            return output_dir / Path(self.output_subfolder) / path
        return output_dir / path
