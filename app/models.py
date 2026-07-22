from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator


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
    status: JobStatus = JobStatus.PENDING
    error: str | None = None

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
        return output_dir / path
