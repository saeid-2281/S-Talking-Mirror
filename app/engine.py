from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.models import AppSettings, JobStatus, TTSJob
from app.providers.base import TTSProvider
from app.services.pronunciation_service import PronunciationService
from app.state import JobStateStore


@dataclass
class RunSummary:
    total: int = 0
    completed: int = 0
    skipped: int = 0
    failed: int = 0


class BatchEngine:
    def __init__(
        self,
        provider: TTSProvider,
        settings: AppSettings,
        output_dir: Path,
        state_store: JobStateStore,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.output_dir = output_dir
        self.state_store = state_store

    def run(self, jobs: list[TTSJob]) -> RunSummary:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        summary = RunSummary(total=len(jobs))

        for index, job in enumerate(jobs, start=1):
            output_path = job.output_path(self.output_dir, self.settings.file_extension)

            if self.state_store.is_completed(job) and output_path.exists():
                job.status = JobStatus.SKIPPED
                summary.skipped += 1
                logger.info("[{}/{}] Resume skip: {}", index, len(jobs), output_path.name)
                continue

            if output_path.exists() and self.settings.skip_existing:
                job.status = JobStatus.SKIPPED
                summary.skipped += 1
                self.state_store.mark_completed(job)
                logger.info("[{}/{}] Existing file skipped: {}", index, len(jobs), output_path.name)
                continue

            try:
                job.status = JobStatus.RUNNING
                logger.info("[{}/{}] Generating: {}", index, len(jobs), output_path.name)
                audio = self.provider.synthesize(PronunciationService().prepare_job(job, self.settings).provider_text, self.settings)
                output_path.write_bytes(audio)
                job.status = JobStatus.COMPLETED
                summary.completed += 1
                self.state_store.mark_completed(job)
                logger.success("Created: {}", output_path)
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)
                summary.failed += 1
                logger.exception("Failed row {} ({}): {}", job.row_number, job.filename, exc)

            if self.settings.delay_seconds and index < len(jobs):
                time.sleep(self.settings.delay_seconds)

        return summary
