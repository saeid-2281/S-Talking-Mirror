from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DevCheckResult:
    started_at: str
    finished_at: str
    elapsed_seconds: float
    success: bool
    exit_code: int
    stage: str
    summary: str
    stdout_path: Path
    stderr_path: Path
    artifact_directory: Path
