from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.models.domain import AppSettings


@dataclass(frozen=True)
class PathValidation:
    missing_csv: bool = False
    missing_output: bool = False

    @property
    def has_missing_paths(self) -> bool:
        return self.missing_csv or self.missing_output

    def messages(self) -> list[str]:
        messages: list[str] = []
        if self.missing_csv:
            messages.append("CSV file is missing")
        if self.missing_output:
            messages.append("Output folder is missing")
        return messages


@dataclass
class ProjectState:
    project_id: int | None
    name: str
    project_file: Path | None
    csv_path: Path | None
    output_path: Path | None
    provider: str
    settings: AppSettings = field(default_factory=lambda: AppSettings(provider="mock"))
    created_at: str | None = None
    updated_at: str | None = None
    dirty: bool = False
    last_saved_at: str | None = None

    @property
    def project_key(self) -> str:
        source = self.project_file or self.csv_path or Path(self.name)
        return f"project:{self.project_id}:{source}"
