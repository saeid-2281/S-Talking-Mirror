from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from app.models.domain import TTSJob


class SourceType(StrEnum):
    CSV = "csv"
    TSV = "tsv"
    XLSX = "xlsx"
    XLSM = "xlsm"


class SourceImportStatus(StrEnum):
    READY = "ready"
    WARNING = "warning"
    ERROR = "error"
    MISSING = "missing"
    CHANGED = "changed"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SourceColumnMapping:
    text_column: str = "text"
    filename_column: str = "filename"
    voice_column: str | None = None
    model_column: str | None = None
    language_column: str | None = None
    output_subfolder_column: str | None = None


@dataclass
class ProjectSource:
    source_id: str
    project_id: int | None
    display_name: str
    source_type: SourceType
    source_path: Path
    worksheet_name: str | None = None
    enabled: bool = True
    import_order: int = 0
    detected_encoding: str | None = None
    detected_delimiter: str | None = None
    mapping: SourceColumnMapping = field(default_factory=SourceColumnMapping)
    row_start: int = 2
    row_end: int | None = None
    imported_at: str | None = None
    last_modified: str | None = None
    source_hash: str | None = None
    import_status: SourceImportStatus = SourceImportStatus.READY
    valid_rows: int = 0
    rejected_rows: int = 0
    issue_count: int = 0

    @property
    def label(self) -> str:
        return f"{self.display_name} / {self.worksheet_name}" if self.worksheet_name else self.display_name


@dataclass(frozen=True)
class SourceImportIssue:
    source_id: str
    severity: str
    code: str
    message: str
    physical_row: int | None = None
    filename: str = ""
    other_source_id: str | None = None


@dataclass
class SourceImportResult:
    source: ProjectSource
    jobs: list[TTSJob] = field(default_factory=list)
    issues: list[SourceImportIssue] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    row_count: int = 0
    preview_rows: list[dict[str, str]] = field(default_factory=list)

    @property
    def can_import(self) -> bool:
        return self.source.enabled and not any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True)
class SourceCollectionImportResult:
    sources: list[SourceImportResult]
    jobs: list[TTSJob]
    collisions: list[SourceImportIssue]

    @property
    def can_import(self) -> bool:
        return all(source.can_import for source in self.sources) and not self.collisions


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
