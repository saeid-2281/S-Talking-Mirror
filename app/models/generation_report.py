from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ReportJob:
    filename: str
    row_number: int
    status: str
    retry_count: int = 0
    duration: float = 0.0
    character_count: int = 0
    error: str = ""
    output_path: str = ""
    original_text: str = ""
    provider_text: str = ""
    pronunciation_aid_applied: bool = False
    pronunciation_strategy: str = "none"
    pronunciation_dictionary: str = ""
    pronunciation_override: str = ""
    language_code: str = ""
    source_id: str = ""
    source_name: str = ""
    source_sheet: str = ""
    source_row: int | None = None
    provider: str = ""
    account_profile_id: str = ""
    model_id: str = ""
    voice_id: str = ""
    usage_amount: float | None = None
    usage_unit: str = "characters"


@dataclass
class GenerationReport:
    report_dir: Path
    summary: dict[str, Any]
    jobs: list[ReportJob] = field(default_factory=list)
    log_events: list[str] = field(default_factory=list)

    @property
    def summary_json(self) -> Path:
        return self.report_dir / "summary.json"

    @property
    def summary_md(self) -> Path:
        return self.report_dir / "summary.md"

    @property
    def report_html(self) -> Path:
        return self.report_dir / "report.html"
