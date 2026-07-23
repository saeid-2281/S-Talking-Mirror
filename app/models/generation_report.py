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
