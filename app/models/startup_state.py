from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StartupRecoveryState:
    temporary_files_removed: int = 0
    running_jobs_recovered: int = 0
    database_ok: bool = True
    migrations_ok: bool = True
    malformed_settings_recovered: bool = False
    invalid_layout_recovered: bool = False
    missing_project_paths: list[str] = field(default_factory=list)
    stale_recent_projects: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    @property
    def action_taken(self) -> bool:
        return any(
            [
                self.temporary_files_removed,
                self.running_jobs_recovered,
                self.malformed_settings_recovered,
                self.invalid_layout_recovered,
                self.missing_project_paths,
                self.stale_recent_projects,
                self.messages,
            ]
        )

    def summary(self) -> str:
        lines: list[str] = []
        if self.temporary_files_removed:
            lines.append(f"Removed {self.temporary_files_removed} stale temporary audio file(s).")
        if self.running_jobs_recovered:
            lines.append(f"Recovered {self.running_jobs_recovered} interrupted running job(s) to Pending.")
        if self.malformed_settings_recovered:
            lines.append("Ignored malformed saved settings.")
        if self.invalid_layout_recovered:
            lines.append("Recovered invalid saved window or dock layout.")
        if self.missing_project_paths:
            lines.append(f"Missing project path(s): {', '.join(self.missing_project_paths)}")
        lines.extend(self.messages)
        return "\n".join(lines)


@dataclass(frozen=True)
class SessionRestoreState:
    auto_restore_enabled: bool
    last_project_path: Path | None = None
    queue_filter: str = "all"
    selected_row: int | None = None
    restored_project: bool = False
    message: str = ""
