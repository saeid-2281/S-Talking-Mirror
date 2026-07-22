from __future__ import annotations

import json
from pathlib import Path

from app.models import JobStatus, TTSJob


class JobStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._completed: set[str] = set()
        self._load()

    @staticmethod
    def _key(job: TTSJob) -> str:
        return f"{job.row_number}:{job.filename}:{job.text}"

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._completed = set(data.get("completed", []))
        except (OSError, json.JSONDecodeError):
            self._completed = set()

    def is_completed(self, job: TTSJob) -> bool:
        return self._key(job) in self._completed

    def mark_completed(self, job: TTSJob) -> None:
        self._completed.add(self._key(job))
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"completed": sorted(self._completed)}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
