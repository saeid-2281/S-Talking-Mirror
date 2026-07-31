from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import Database
from app.exceptions import ProviderError
from app.models import AppSettings, FailureCategory, JobStatus, TTSJob
from app.repositories.job_repository import JobRepository
from app.services.failure_analysis_service import FailureAnalysisService, RetryPolicyService
from app.services.generation_monitor_service import GenerationMonitorService
from app.services.queue_service import QueueService


def _project(database: Database) -> int:
    with database.transaction() as connection:
        cursor = connection.execute(
            """
            INSERT INTO projects(
                name, project_file, csv_path, output_path, provider,
                settings_json, created_at, updated_at
            )
            VALUES('Phase 4', NULL, NULL, NULL, 'mock', '{}', 'now', 'now')
            """
        )
        return int(cursor.lastrowid)


def test_phase4_classifies_transient_and_permanent_failures() -> None:
    service = FailureAnalysisService()
    transient = service.analyze(
        ProviderError(
            "Service temporarily unavailable request 12345",
            retryable=True,
            http_status=503,
            provider_code="service_unavailable",
        )
    )
    same_failure = service.analyze(
        ProviderError(
            "Service temporarily unavailable request 98765",
            retryable=True,
            http_status=503,
            provider_code="service_unavailable",
        )
    )
    permanent = service.analyze(
        ProviderError(
            "Invalid API key",
            retryable=False,
            http_status=401,
            provider_code="invalid_api_key",
        )
    )

    assert transient.category == FailureCategory.SERVER
    assert transient.retryable is True
    assert transient.fingerprint == same_failure.fingerprint
    assert permanent.category == FailureCategory.AUTHENTICATION
    assert permanent.retryable is False
    assert permanent.permanent is True


def test_phase4_retry_policy_backoff_limit_and_manual_override() -> None:
    now = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)
    transient = TTSJob(
        row_number=1,
        filename="transient.wav",
        text="one",
        status=JobStatus.FAILED,
        retry_count=2,
        failure_category=FailureCategory.NETWORK,
        retryable=True,
    )
    permanent = TTSJob(
        row_number=2,
        filename="permanent.wav",
        text="two",
        status=JobStatus.FAILED,
        retry_count=1,
        failure_category=FailureCategory.AUTHENTICATION,
        retryable=False,
    )
    exhausted = TTSJob(
        row_number=3,
        filename="exhausted.wav",
        text="three",
        status=JobStatus.FAILED,
        retry_count=4,
        failure_category=FailureCategory.SERVER,
        retryable=True,
        retry_exhausted=True,
    )
    service = RetryPolicyService(base_delay_seconds=2, maximum_delay_seconds=60)

    result = service.prepare([transient, permanent, exhausted], max_retries=4, now=now)

    assert result.scheduled == 1
    assert result.blocked_reasons == {"permanent_failure": 1, "retry_limit": 1}
    assert transient.status == JobStatus.PENDING
    assert transient.next_retry_at == "2026-07-30T08:00:04+00:00"
    assert transient.retry_history[-1].event == "retry_scheduled"
    override = service.prepare(
        [permanent, exhausted],
        max_retries=4,
        manual_override=True,
        now=now,
    )
    assert override.scheduled == 2
    assert all(job.status == JobStatus.PENDING for job in (permanent, exhausted))
    assert all(job.next_retry_at == now.isoformat() for job in (permanent, exhausted))


def test_phase4_queue_retry_state_survives_database_round_trip(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase4.db")
    database.initialize()
    project_id = _project(database)
    repository = JobRepository(database)
    job = TTSJob(
        row_number=2,
        filename="network.wav",
        text="hello",
        status=JobStatus.FAILED,
        error="Network timeout [code=timeout status=503]",
        retry_count=1,
    )
    repository.upsert_jobs(project_id, [job])
    queue = repository.restore_jobs(project_id)
    service = QueueService(repository)

    result = service.retry_jobs(project_id, queue, queue, max_retries=4, transient_only=True)
    restored = repository.restore_jobs(project_id)

    assert result.scheduled == 1
    assert restored[0].status == JobStatus.PENDING
    assert restored[0].failure_category in {FailureCategory.NETWORK, FailureCategory.SERVER}
    assert restored[0].error_fingerprint
    assert restored[0].next_retry_at
    assert restored[0].retry_history[-1].event == "retry_scheduled"


def test_phase4_failure_report_exports_json_and_csv(tmp_path: Path) -> None:
    job = TTSJob(
        row_number=8,
        filename="failed.wav",
        text="hello",
        status=JobStatus.FAILED,
        error="Invalid API key",
        retry_count=1,
        failure_category=FailureCategory.AUTHENTICATION,
        error_code="invalid_api_key",
        error_fingerprint="abc123",
        retryable=False,
    )

    json_path, csv_path = FailureAnalysisService.export_report(
        [job],
        tmp_path,
        project_name="Phase 4",
    )

    assert json_path.exists()
    assert csv_path.exists()
    assert '"authentication"' in json_path.read_text(encoding="utf-8")
    assert "abc123" in csv_path.read_text(encoding="utf-8-sig")


def test_phase4_monitor_exposes_retry_countdown(qt_app, tmp_path: Path) -> None:
    service = GenerationMonitorService(clock=lambda: 10.0)
    job = TTSJob(row_number=1, filename="retry.wav", text="hello")
    settings = AppSettings(provider="mock")
    service.start_run(
        [job],
        provider="Mock",
        output_dir=tmp_path,
        settings=settings,
        project_key="phase4",
    )

    state = service.handle_progress(
        [job],
        status="retrying",
        name="retry.wav",
        duration=12.0,
        retry=2,
        error="Retry in 12s",
    )

    assert state.current_status == "Retrying"
    assert state.current_filename == "retry.wav"
    assert state.retry_countdown_seconds == 12.0
    assert state.current_attempt == 2
    service.reset()
