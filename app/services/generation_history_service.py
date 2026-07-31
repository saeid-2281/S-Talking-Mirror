from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models.generation_history import GenerationHistorySummary, GenerationSessionComparison
from app.models.generation_performance import (
    GenerationPerformanceAnalysis,
    GenerationPerformanceBudget,
    GenerationPerformanceTrend,
)
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_performance_policy_service import (
    GenerationPerformancePolicyService,
)
from app.services.generation_performance_service import GenerationPerformanceService


class GenerationHistoryService:
    """Query, summarize, compare, analyze, and export generation sessions."""

    def __init__(
        self,
        repository: ProductEventRepository,
        performance_service: GenerationPerformanceService | None = None,
        policy_service: GenerationPerformancePolicyService | None = None,
    ) -> None:
        self.repository = repository
        self.policy_service = policy_service or GenerationPerformancePolicyService(repository)
        self.performance_service = performance_service or GenerationPerformanceService(
            repository,
            policy_service=self.policy_service,
        )

    def list_sessions(
        self,
        *,
        project_id: int | None = None,
        provider: str | None = None,
        result: str | None = None,
        limit: int = 250,
    ) -> list[BatchSessionRecord]:
        return self.repository.list_batch_sessions(
            project_id=project_id,
            provider=provider,
            result=result,
            limit=limit,
        )

    def reanalyze(
        self,
        records: Iterable[BatchSessionRecord],
    ) -> list[GenerationPerformanceAnalysis]:
        return self.performance_service.reanalyze(records)

    def trend(
        self,
        records: Iterable[BatchSessionRecord],
        *,
        window_size: int = 10,
    ) -> GenerationPerformanceTrend:
        return self.performance_service.trend(records, window_size=window_size)

    def performance_budget(self, project_id: int | None) -> GenerationPerformanceBudget:
        return self.policy_service.budget_for(project_id)

    def save_performance_budget(
        self,
        budget: GenerationPerformanceBudget,
    ) -> GenerationPerformanceBudget:
        return self.policy_service.save_budget(budget)

    def silence_alerts(
        self,
        project_id: int | None,
        *,
        minutes: int = 60,
    ) -> GenerationPerformanceBudget:
        return self.policy_service.silence(project_id, minutes=minutes)

    def resume_alerts(self, project_id: int | None) -> GenerationPerformanceBudget:
        return self.policy_service.resume(project_id)

    def acknowledge_alerts(self, session_ids: Iterable[str]) -> int:
        return self.policy_service.acknowledge(session_ids)

    @staticmethod
    def summary(records: Iterable[BatchSessionRecord]) -> GenerationHistorySummary:
        sessions = list(records)
        session_count = len(sessions)
        total_jobs = sum(max(0, session.total_jobs) for session in sessions)
        completed_jobs = sum(max(0, session.completed_jobs) for session in sessions)
        failed_jobs = sum(max(0, session.failed_jobs) for session in sessions)
        skipped_jobs = sum(max(0, session.skipped_jobs) for session in sessions)
        elapsed_seconds = sum(max(0.0, session.elapsed_seconds) for session in sessions)
        active_seconds = sum(max(0.0, session.active_seconds) for session in sessions)
        completion_rate = (completed_jobs / total_jobs * 100.0) if total_jobs else 0.0
        throughput_records = [session for session in sessions if session.files_per_minute > 0]
        character_rate_records = [session for session in sessions if session.characters_per_minute > 0]
        health_records = [
            session
            for session in sessions
            if session.health_score > 0
            or session.regression_severity in {"none", "warning", "critical"}
        ]
        return GenerationHistorySummary(
            session_count=session_count,
            total_jobs=total_jobs,
            completed_jobs=completed_jobs,
            failed_jobs=failed_jobs,
            skipped_jobs=skipped_jobs,
            total_characters=sum(max(0, session.character_count) for session in sessions),
            retry_events=sum(max(0, session.retry_events) for session in sessions),
            elapsed_seconds=elapsed_seconds,
            active_seconds=active_seconds,
            completion_rate=completion_rate,
            average_elapsed_seconds=(elapsed_seconds / session_count) if session_count else 0.0,
            average_files_per_minute=(
                sum(session.files_per_minute for session in throughput_records) / len(throughput_records)
                if throughput_records
                else 0.0
            ),
            average_characters_per_minute=(
                sum(session.characters_per_minute for session in character_rate_records)
                / len(character_rate_records)
                if character_rate_records
                else 0.0
            ),
            average_health_score=(
                sum(session.health_score for session in health_records) / len(health_records)
                if health_records
                else 0.0
            ),
            warning_regressions=sum(
                session.regression_severity == "warning" for session in sessions
            ),
            critical_regressions=sum(
                session.regression_severity == "critical" for session in sessions
            ),
            insufficient_baselines=sum(
                session.regression_severity == "insufficient_data" for session in sessions
            ),
            providers=dict(sorted(Counter(session.provider for session in sessions).items())),
            results=dict(sorted(Counter(session.result for session in sessions).items())),
        )

    @staticmethod
    def compare(
        baseline: BatchSessionRecord,
        candidate: BatchSessionRecord,
    ) -> GenerationSessionComparison:
        return GenerationSessionComparison(
            baseline_session_id=baseline.session_id,
            candidate_session_id=candidate.session_id,
            completion_rate_delta=(
                GenerationHistoryService._completion_rate(candidate)
                - GenerationHistoryService._completion_rate(baseline)
            ),
            elapsed_seconds_delta=candidate.elapsed_seconds - baseline.elapsed_seconds,
            files_per_minute_delta=candidate.files_per_minute - baseline.files_per_minute,
            characters_per_minute_delta=(
                candidate.characters_per_minute - baseline.characters_per_minute
            ),
            retry_events_delta=candidate.retry_events - baseline.retry_events,
            failed_jobs_delta=candidate.failed_jobs - baseline.failed_jobs,
            health_score_delta=candidate.health_score - baseline.health_score,
        )

    @staticmethod
    def export(
        records: Iterable[BatchSessionRecord],
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        sessions = list(records)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "history"
        json_path = directory / f"generation-history-{safe_name}-{stamp}.json"
        csv_path = directory / f"generation-history-{safe_name}-{stamp}.csv"
        summary = GenerationHistoryService.summary(sessions)
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project": project_name,
            "summary": summary.__dict__,
            "sessions": [GenerationHistoryService._record_payload(record) for record in sessions],
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            fieldnames = [
                "session_id",
                "project_id",
                "started_at",
                "finished_at",
                "result",
                "scope",
                "provider",
                "model",
                "voice",
                "total_jobs",
                "completed_jobs",
                "failed_jobs",
                "skipped_jobs",
                "character_count",
                "retry_events",
                "elapsed_seconds",
                "active_seconds",
                "paused_seconds",
                "files_per_minute",
                "characters_per_minute",
                "health_score",
                "baseline_session_id",
                "regression_severity",
                "report_path",
                "output_path",
                "failure_summary_json",
                "monitor_metrics_json",
                "regression_reasons_json",
                "baseline_metrics_json",
                "performance_deltas_json",
                "alert_fingerprint",
                "alert_state",
                "alert_notification_id",
                "alert_created_at",
                "alert_acknowledged_at",
                "incident_id",
                "incident_status",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for record in sessions:
                row = GenerationHistoryService._record_payload(record)
                row.pop("failure_summary", None)
                row.pop("monitor_metrics", None)
                row.pop("regression_reasons", None)
                row.pop("baseline_metrics", None)
                row.pop("performance_deltas", None)
                row["failure_summary_json"] = json.dumps(
                    record.failure_summary,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                row["monitor_metrics_json"] = json.dumps(
                    record.monitor_metrics,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                row["regression_reasons_json"] = json.dumps(
                    record.regression_reasons,
                    ensure_ascii=False,
                )
                row["baseline_metrics_json"] = json.dumps(
                    record.baseline_metrics,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                row["performance_deltas_json"] = json.dumps(
                    record.performance_deltas,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                writer.writerow(row)
        return json_path, csv_path

    @staticmethod
    def _completion_rate(record: BatchSessionRecord) -> float:
        return (record.completed_jobs / record.total_jobs * 100.0) if record.total_jobs else 0.0

    @staticmethod
    def _record_payload(record: BatchSessionRecord) -> dict[str, object]:
        return {
            "session_id": record.session_id,
            "project_id": record.project_id,
            "scope": record.scope,
            "provider": record.provider,
            "model": record.model,
            "voice": record.voice,
            "total_jobs": record.total_jobs,
            "completed_jobs": record.completed_jobs,
            "failed_jobs": record.failed_jobs,
            "skipped_jobs": record.skipped_jobs,
            "character_count": record.character_count,
            "report_path": record.report_path,
            "output_path": record.output_path,
            "result": record.result,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "elapsed_seconds": record.elapsed_seconds,
            "active_seconds": record.active_seconds,
            "paused_seconds": record.paused_seconds,
            "retry_events": record.retry_events,
            "files_per_minute": record.files_per_minute,
            "characters_per_minute": record.characters_per_minute,
            "failure_summary": record.failure_summary,
            "monitor_metrics": record.monitor_metrics,
            "health_score": record.health_score,
            "baseline_session_id": record.baseline_session_id,
            "regression_severity": record.regression_severity,
            "regression_reasons": record.regression_reasons,
            "baseline_metrics": record.baseline_metrics,
            "performance_deltas": record.performance_deltas,
            "alert_fingerprint": record.alert_fingerprint,
            "alert_state": record.alert_state,
            "alert_notification_id": record.alert_notification_id,
            "alert_created_at": record.alert_created_at,
            "alert_acknowledged_at": record.alert_acknowledged_at,
            "incident_id": record.incident_id,
            "incident_status": record.incident_status,
        }
