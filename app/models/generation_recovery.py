from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GenerationRecoverySnapshot:
    version: int
    saved_at: str
    project_key: str
    provider: str
    profile_id: str | None
    model_id: str
    voice_id: str
    output_dir: str
    session: dict[str, Any]
    jobs: tuple[dict[str, Any], ...]
    checksum: str

    @property
    def resumable_jobs(self) -> int:
        return sum(
            str(job.get("status")) in {"pending", "running", "failed"}
            for job in self.jobs
        )
