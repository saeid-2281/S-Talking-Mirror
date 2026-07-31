from __future__ import annotations

from pathlib import Path

import pytest

from app.models import AppSettings, GenerationSession, JobStatus, TTSJob
from app.services.generation_monitor_service import GenerationMonitorService


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def jobs(count: int = 4) -> list[TTSJob]:
    return [
        TTSJob(row_number=i + 1, filename=f"{i + 1}.wav", text="text" * (i + 1))
        for i in range(count)
    ]


def test_generation_session_counts_progress() -> None:
    values = jobs(3)
    values[0].status = JobStatus.COMPLETED
    values[1].status = JobStatus.FAILED
    session = GenerationSession.build(
        session_id="run-1",
        status="Running",
        started_at="now",
        jobs=values,
        elapsed_seconds=10,
        active_seconds=8,
        retried_jobs=2,
        jobs_per_minute=15,
        characters_per_second=20,
        eta_seconds=12,
        stalled=False,
    )
    assert session.processed_jobs == 2
    assert session.retried_jobs == 2
    assert session.progress_percent == pytest.approx(66.666, rel=0.01)


def test_monitor_tracks_throughput_retry_and_eta() -> None:
    clock = Clock()
    service = GenerationMonitorService(clock=clock)
    values = jobs(3)
    service.start_run(values, provider="mock", output_dir=Path("out"), settings=AppSettings(provider="mock"))
    clock.advance(10)
    values[0].status = JobStatus.COMPLETED
    values[0].retry_count = 2
    state = service.handle_progress(
        values, status="completed", name="1.wav", duration=2, retry=2, error=""
    )
    assert state.retries == 2
    assert state.jobs_per_minute == pytest.approx(6.0)
    assert state.characters_per_second == pytest.approx(values[0].character_count / 10)
    assert state.remaining_eta_seconds > 0


def test_monitor_detects_stalled_generation() -> None:
    clock = Clock()
    service = GenerationMonitorService(clock=clock)
    service.stall_threshold_seconds = 5
    values = jobs(2)
    values[0].status = JobStatus.RUNNING
    service.start_run(values, provider="mock", output_dir=Path("out"), settings=AppSettings(provider="mock"))
    clock.advance(6)
    state = service.tick()
    assert state.stalled
    assert state.worker_state == "Stalled"


def test_session_snapshot_matches_state() -> None:
    clock = Clock()
    service = GenerationMonitorService(clock=clock)
    values = jobs(2)
    service.start_run(values, provider="mock", output_dir=Path("out"), settings=AppSettings(provider="mock"))
    clock.advance(3)
    service.tick()
    snapshot = service.session_snapshot()
    assert snapshot.session_id != "idle"
    assert snapshot.total_jobs == 2
    assert snapshot.elapsed_seconds == 3
