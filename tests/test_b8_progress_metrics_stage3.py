"""Roadmap 2 B8.2B Stage 3A: live GUI metrics avoid a second SQLite read."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from app.models.domain import JobStatus, TTSJob
from app.services.queue_service import QueueService


class _AverageRepository:
    def __init__(self, value=12.0):
        self.value = value
        self.calls = []

    def average_completed_duration(self, project_id):
        self.calls.append(project_id)
        return self.value


class ProgressMetricsStage3Tests(unittest.TestCase):
    @staticmethod
    def _jobs():
        return [
            TTSJob(row_number=1, filename='one', text='one', status=JobStatus.COMPLETED, duration_seconds=4.0),
            TTSJob(row_number=2, filename='two', text='two', status=JobStatus.COMPLETED, duration_seconds=6.0),
            TTSJob(row_number=3, filename='three', text='three', status=JobStatus.RUNNING),
            TTSJob(row_number=4, filename='four', text='four', status=JobStatus.PENDING),
            TTSJob(row_number=5, filename='five', text='five', status=JobStatus.FAILED),
        ]

    def test_active_metrics_keep_queue_counts_and_use_in_memory_duration(self):
        repo = _AverageRepository()
        service = QueueService(repo)
        metrics = service.metrics(self._jobs(), project_id=7, use_repository_average=False)
        self.assertEqual((metrics.total, metrics.processed, metrics.completed, metrics.failed,
                          metrics.pending, metrics.running), (5, 3, 2, 1, 1, 1))
        self.assertEqual(metrics.eta_seconds, 10.0)
        self.assertEqual(repo.calls, [])

    def test_idle_metrics_keep_original_repository_average(self):
        repo = _AverageRepository(value=12)
        metrics = QueueService(repo).metrics(self._jobs(), project_id=17)
        self.assertEqual(metrics.eta_seconds, 24.0)
        self.assertEqual(repo.calls, [17])

    def test_no_completed_samples_uses_existing_fallback_without_disk(self):
        repo = _AverageRepository()
        jobs = [TTSJob(row_number=1, filename='one', text='one', status=JobStatus.PENDING),
                TTSJob(row_number=2, filename='two', text='two', status=JobStatus.COMPLETED, duration_seconds=0.0)]
        metrics = QueueService(repo, fallback_seconds_per_job=3.5).metrics(
            jobs, project_id=9, use_repository_average=False,
        )
        self.assertEqual(metrics.eta_seconds, 3.5)
        self.assertEqual(repo.calls, [])

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt integration requires Windows PySide6 environment')
    def test_controller_routes_live_and_idle_metrics_without_changing_status(self):
        from app.controllers.generation_controller import GenerationController

        controller = GenerationController(Path('not-used-in-this-test.sqlite'))
        controller.set_jobs(self._jobs(), project_id=None)
        repo = _AverageRepository(value=12)
        controller.queue_service.repository = repo
        controller.current_project_id = 7
        controller.worker = object()  # Active state without starting any provider or worker.
        live = controller.metrics()
        self.assertEqual(live.eta_seconds, 10)
        self.assertEqual(repo.calls, [])
        controller.worker = None
        idle = controller.metrics()
        self.assertEqual(idle.eta_seconds, 24)
        self.assertEqual(repo.calls, [7])

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt integration requires Windows PySide6 environment')
    def test_progress_index_cache_uses_first_matching_row_and_falls_back(self):
        from app.controllers.generation_controller import GenerationController

        controller = GenerationController(Path('not-used-in-this-test.sqlite'))
        jobs = self._jobs()
        controller.set_jobs(jobs)
        controller._job_index_by_row = {job.row_number: index for index, job in enumerate(jobs)}
        self.assertEqual(controller._job_index(jobs[4]), 4)
        controller._job_index_by_row = {jobs[4].row_number: 0}  # Corrupt/stale index.
        self.assertEqual(controller._job_index(jobs[4]), 4)
        self.assertEqual(controller._job_index(None), -1)
