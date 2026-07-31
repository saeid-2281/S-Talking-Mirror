from __future__ import annotations

from pathlib import Path

from app.models import AppSettings, GenerationSession, JobStatus, TTSJob
from app.services.generation_recovery_service import GenerationRecoveryService


def _session() -> GenerationSession:
    return GenerationSession(
        session_id="phase3",
        status="Running",
        started_at="now",
        updated_at="now",
        total_jobs=3,
        pending_jobs=1,
        running_jobs=1,
        completed_jobs=0,
        failed_jobs=1,
        skipped_jobs=0,
        retried_jobs=0,
        processed_jobs=0,
        total_characters=12,
        processed_characters=0,
        elapsed_seconds=1,
        active_seconds=1,
        jobs_per_minute=0,
        characters_per_second=0,
        eta_seconds=1,
        progress_percent=25,
        stalled=False,
    )


def _snapshot(service: GenerationRecoveryService, tmp_path: Path):
    settings=AppSettings(
        provider="elevenlabs",
        active_api_profile_id="profile-a",
        model_id="model-a",
        voice_id="voice-a",
    )
    return service.save(
        session=_session(),
        jobs=[
            TTSJob(row_number=1,filename="1.wav",text="one",status=JobStatus.RUNNING),
            TTSJob(row_number=2,filename="2.wav",text="two",status=JobStatus.FAILED,error="x"),
            TTSJob(row_number=3,filename="3.wav",text="three",status=JobStatus.PENDING),
        ],
        settings=settings,
        output_dir=tmp_path/"out",
        project_key="project-a",
    ),settings


def test_phase3_reports_exact_compatibility_mismatches(tmp_path: Path) -> None:
    service=GenerationRecoveryService(tmp_path/"recovery.json")
    snapshot,settings=_snapshot(service,tmp_path)
    assert service.incompatibility_reason(snapshot,settings=settings,project_key="project-a")==""
    changed=settings.model_copy(update={"voice_id":"voice-b","model_id":"model-b"})
    assert service.incompatibility_reason(
        snapshot,settings=changed,project_key="other"
    )=="Snapshot mismatch: project, model, voice."


def test_phase3_resume_pending_preserves_failed_job(tmp_path: Path) -> None:
    service=GenerationRecoveryService(tmp_path/"recovery.json")
    snapshot,_=_snapshot(service,tmp_path)
    jobs=service.restore_jobs(snapshot,retry_failed=False)
    assert [job.status for job in jobs]==[
        JobStatus.PENDING,JobStatus.FAILED,JobStatus.PENDING
    ]


def test_phase3_resume_retry_failed_resets_failure(tmp_path: Path) -> None:
    service=GenerationRecoveryService(tmp_path/"recovery.json")
    snapshot,_=_snapshot(service,tmp_path)
    jobs=service.restore_jobs(snapshot,retry_failed=True)
    assert all(job.status==JobStatus.PENDING for job in jobs)
    assert jobs[1].error is None
