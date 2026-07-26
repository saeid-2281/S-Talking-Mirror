from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.models.domain import TTSJob


@dataclass(frozen=True)
class CsvImportIssue:
    physical_row: int | None
    parsed_row: int | None
    severity: str
    issue_code: str
    raw_row_excerpt: str
    parsed_filename: str
    parsed_text_excerpt: str
    problem: str
    suggested_action: str


@dataclass
class CsvImportState:
    source_path: Path
    detected_encoding: str = ""
    detected_delimiter: str = ","
    header_names: list[str] = field(default_factory=list)
    expected_columns: list[str] = field(default_factory=lambda: ["filename", "text"])
    total_physical_rows: int = 0
    parsed_rows: int = 0
    valid_rows: int = 0
    rejected_rows: int = 0
    malformed_rows: list[int] = field(default_factory=list)
    extra_column_rows: list[int] = field(default_factory=list)
    missing_column_rows: list[int] = field(default_factory=list)
    duplicate_filename_rows: list[int] = field(default_factory=list)
    filename_looks_like_prose_rows: list[int] = field(default_factory=list)
    text_looks_like_filename_rows: list[int] = field(default_factory=list)
    issues: list[CsvImportIssue] = field(default_factory=list)
    jobs: list[TTSJob] = field(default_factory=list)
    can_import: bool = False
    repaired_preview_path: Path | None = None
    rejected_rows_path: Path | None = None
