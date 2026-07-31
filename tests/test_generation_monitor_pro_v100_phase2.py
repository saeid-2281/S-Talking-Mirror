from __future__ import annotations

import json
from pathlib import Path

from app.models import AppSettings, GenerationSession, JobStatus, TTSJob
from app.services.generation_recovery_service import GenerationRecoveryService


def _session() -> GenerationSession:
    return GenerationSession(
        session_id="run-1",
        status="Running",
        started_at="now",
        updated_at="now",
        total_jobs=2,
        pending_jobs=1,
        running_jobs=1,
        completed_jobs=0,
        failed_jobs=0,
        skipped_jobs=0,
        retried_jobs=0,
        processed_jobs=0,
        total_characters=8,
        processed_characters=0,
        elapsed_seconds=2,
        active_seconds=2,
        jobs_per_minute=0,
        characters_per_second=0,
        eta_seconds=4,
        progress_percent=0,
        stalled=False,
    )


def _jobs() -> list[TTSJob]:
    return [
        TTSJob(row_number=1, filename="1.wav", text="Hej", status=JobStatus.RUNNING),
        TTSJob(row_number=2, filename="2.wav", text="Verden", status=JobStatus.FAILED, error="x"),
    ]


def test_recovery_round_trip_and_atomic_checksum(tmp_path: Path) -> None:
    service = GenerationRecoveryService(tmp_path / "recovery.json")
    settings = AppSettings(provider="mock", active_api_profile_id="a")
    saved = service.save(
        session=_session(),
        jobs=_jobs(),
        settings=settings,
        output_dir=tmp_path / "out",
        project_key="project-1",
    )
    loaded = service.load()
    assert loaded == saved
    assert loaded is not None
    assert loaded.resumable_jobs == 2
    assert not (tmp_path / "recovery.json.tmp").exists()


def test_recovery_rejects_tampered_payload(tmp_path: Path) -> None:
    service = GenerationRecoveryService(tmp_path / "recovery.json")
    service.save(
        session=_session(),
        jobs=_jobs(),
        settings=AppSettings(provider="mock"),
        output_dir=tmp_path,
        project_key="p",
    )
    payload = json.loads(service.path.read_text(encoding="utf-8"))
    payload["provider"] = "elevenlabs"
    service.path.write_text(json.dumps(payload), encoding="utf-8")
    assert service.load() is None


def test_restore_converts_interrupted_and_optionally_failed_jobs(tmp_path: Path) -> None:
    service = GenerationRecoveryService(tmp_path / "recovery.json")
    snapshot = service.save(
        session=_session(),
        jobs=_jobs(),
        settings=AppSettings(provider="mock"),
        output_dir=tmp_path,
        project_key="p",
    )
    normal = service.restore_jobs(snapshot)
    assert normal[0].status == JobStatus.PENDING
    assert normal[1].status == JobStatus.FAILED
    retried = service.restore_jobs(snapshot, retry_failed=True)
    assert [job.status for job in retried] == [JobStatus.PENDING, JobStatus.PENDING]


def test_recovery_requires_matching_project_and_provider_identity(tmp_path: Path) -> None:
    service = GenerationRecoveryService(tmp_path / "recovery.json")
    settings = AppSettings(
        provider="elevenlabs",
        active_api_profile_id="profile-a",
        model_id="model-a",
        voice_id="voice-a",
    )
    snapshot = service.save(
        session=_session(),
        jobs=_jobs(),
        settings=settings,
        output_dir=tmp_path,
        project_key="project-a",
    )
    assert service.is_compatible(snapshot, settings=settings, project_key="project-a")
    changed = settings.model_copy(update={"active_api_profile_id": "profile-b"})
    assert not service.is_compatible(snapshot, settings=changed, project_key="project-a")
