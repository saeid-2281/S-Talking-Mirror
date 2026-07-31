from __future__ import annotations

import statistics
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, Iterable

from app.models.generation_performance import (
    GenerationPerformanceAnalysis,
    GenerationPerformanceBaseline,
    GenerationPerformanceThresholds,
    GenerationPerformanceTrend,
)
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository

if TYPE_CHECKING:
    from app.services.generation_performance_policy_service import (
        GenerationPerformancePolicyService,
    )


class GenerationPerformanceService:
    """Build rolling baselines and detect generation-performance regressions."""

    def __init__(
        self,
        repository: ProductEventRepository,
        thresholds: GenerationPerformanceThresholds | None = None,
        policy_service: GenerationPerformancePolicyService | None = None,
    ) -> None:
        self.repository = repository
        self.thresholds = thresholds or GenerationPerformanceThresholds()
        self.policy_service = policy_service

    def analyze_and_persist(self, record: BatchSessionRecord) -> GenerationPerformanceAnalysis:
        thresholds = self._thresholds_for(record.project_id)
        history = self.repository.list_batch_sessions(
            project_id=record.project_id,
            provider=record.provider,
            limit=max(100, thresholds.baseline_window_size * 5),
        )
        analysis = self.analyze(record, history, thresholds=thresholds)
        self.repository.update_batch_performance(
            record.session_id,
            health_score=analysis.health_score,
            baseline_session_id=analysis.baseline_session_id,
            regression_severity=analysis.severity,
            regression_reasons=list(analysis.reasons),
            baseline_metrics=asdict(analysis.baseline),
            performance_deltas=analysis.deltas,
        )
        return analysis

    def analyze(
        self,
        record: BatchSessionRecord,
        history: Iterable[BatchSessionRecord],
        *,
        thresholds: GenerationPerformanceThresholds | None = None,
    ) -> GenerationPerformanceAnalysis:
        active_thresholds = thresholds or self._thresholds_for(record.project_id)
        comparable = self._comparable_history(record, history, active_thresholds)
        baseline = self.build_baseline(comparable, thresholds=active_thresholds)
        own_health = self.health_score(record)
        if baseline.sample_count < active_thresholds.minimum_baseline_sessions:
            return GenerationPerformanceAnalysis(
                session_id=record.session_id,
                health_score=own_health,
                severity="insufficient_data",
                baseline_session_id=comparable[0].session_id if comparable else None,
                baseline=baseline,
            )

        metrics = self._metrics(record)
        deltas = {
            "completion_rate_delta": metrics["completion_rate"] - baseline.completion_rate,
            "failure_rate_delta": metrics["failure_rate"] - baseline.failure_rate,
            "seconds_per_job_ratio": self._ratio_delta(
                metrics["seconds_per_job"],
                baseline.seconds_per_job,
            ),
            "files_per_minute_ratio": self._ratio_delta(
                metrics["files_per_minute"],
                baseline.files_per_minute,
            ),
            "characters_per_minute_ratio": self._ratio_delta(
                metrics["characters_per_minute"],
                baseline.characters_per_minute,
            ),
            "retry_rate_delta": metrics["retries_per_100_jobs"] - baseline.retries_per_100_jobs,
        }
        warnings: list[str] = []
        criticals: list[str] = []
        self._classify_completion(
            deltas["completion_rate_delta"], warnings, criticals, active_thresholds
        )
        self._classify_failure(
            deltas["failure_rate_delta"], warnings, criticals, active_thresholds
        )
        throughput_delta = self._throughput_delta(deltas)
        self._classify_throughput(
            throughput_delta, warnings, criticals, active_thresholds
        )
        self._classify_elapsed(
            deltas["seconds_per_job_ratio"], warnings, criticals, active_thresholds
        )
        self._classify_retry(
            deltas["retry_rate_delta"], warnings, criticals, active_thresholds
        )
        if record.result == "failed" and "Session result is failed" not in criticals:
            criticals.append("Session result is failed")

        severity = "critical" if criticals else "warning" if warnings else "none"
        reasons = tuple(criticals + warnings)
        penalty = 15.0 * len(warnings) + 28.0 * len(criticals)
        health_score = max(0.0, min(100.0, own_health - penalty))
        return GenerationPerformanceAnalysis(
            session_id=record.session_id,
            health_score=round(health_score, 1),
            severity=severity,
            reasons=reasons,
            baseline_session_id=comparable[0].session_id if comparable else None,
            baseline=baseline,
            deltas={key: round(value, 6) for key, value in deltas.items()},
        )

    def build_baseline(
        self,
        records: Iterable[BatchSessionRecord],
        *,
        thresholds: GenerationPerformanceThresholds | None = None,
    ) -> GenerationPerformanceBaseline:
        active_thresholds = thresholds or self.thresholds
        sessions = list(records)[: active_thresholds.baseline_window_size]
        if not sessions:
            return GenerationPerformanceBaseline()
        metrics = [self._metrics(record) for record in sessions]
        return GenerationPerformanceBaseline(
            sample_count=len(sessions),
            session_ids=tuple(record.session_id for record in sessions),
            completion_rate=self._median(item["completion_rate"] for item in metrics),
            failure_rate=self._median(item["failure_rate"] for item in metrics),
            seconds_per_job=self._median(
                (item["seconds_per_job"] for item in metrics),
                positive_only=True,
            ),
            files_per_minute=self._median(
                (item["files_per_minute"] for item in metrics),
                positive_only=True,
            ),
            characters_per_minute=self._median(
                (item["characters_per_minute"] for item in metrics),
                positive_only=True,
            ),
            retries_per_100_jobs=self._median(
                item["retries_per_100_jobs"] for item in metrics
            ),
        )

    def reanalyze(self, records: Iterable[BatchSessionRecord]) -> list[GenerationPerformanceAnalysis]:
        ordered = sorted(records, key=lambda item: item.started_at)
        analyses: list[GenerationPerformanceAnalysis] = []
        prior: list[BatchSessionRecord] = []
        for record in ordered:
            analysis = self.analyze(
                record,
                prior,
                thresholds=self._thresholds_for(record.project_id),
            )
            self.repository.update_batch_performance(
                record.session_id,
                health_score=analysis.health_score,
                baseline_session_id=analysis.baseline_session_id,
                regression_severity=analysis.severity,
                regression_reasons=list(analysis.reasons),
                baseline_metrics=asdict(analysis.baseline),
                performance_deltas=analysis.deltas,
            )
            analyses.append(analysis)
            prior.append(
                replace(
                    record,
                    health_score=analysis.health_score,
                    baseline_session_id=analysis.baseline_session_id,
                    regression_severity=analysis.severity,
                    regression_reasons=list(analysis.reasons),
                    baseline_metrics=asdict(analysis.baseline),
                    performance_deltas=analysis.deltas,
                )
            )
        return analyses

    def trend(self, records: Iterable[BatchSessionRecord], *, window_size: int = 10) -> GenerationPerformanceTrend:
        sessions = sorted(records, key=lambda item: item.started_at, reverse=True)[: max(2, window_size)]
        if not sessions:
            return GenerationPerformanceTrend()
        scores = [self._score_for_record(record) for record in sessions]
        midpoint = max(1, len(scores) // 2)
        recent = scores[:midpoint]
        previous = scores[midpoint:] or recent
        recent_average = sum(recent) / len(recent)
        previous_average = sum(previous) / len(previous)
        delta = recent_average - previous_average
        direction = "improving" if delta >= 5.0 else "degrading" if delta <= -5.0 else "stable"
        best = max(sessions, key=self._score_for_record)
        worst = min(sessions, key=self._score_for_record)
        return GenerationPerformanceTrend(
            direction=direction,
            session_count=len(sessions),
            recent_average_health=round(recent_average, 1),
            previous_average_health=round(previous_average, 1),
            health_delta=round(delta, 1),
            warning_count=sum(record.regression_severity == "warning" for record in sessions),
            critical_count=sum(record.regression_severity == "critical" for record in sessions),
            best_session_id=best.session_id,
            worst_session_id=worst.session_id,
        )

    def _score_for_record(self, record: BatchSessionRecord) -> float:
        if record.health_score > 0 or record.regression_severity in {"none", "warning", "critical"}:
            return record.health_score
        return self.health_score(record)

    @staticmethod
    def health_score(record: BatchSessionRecord) -> float:
        total = max(0, record.total_jobs)
        completion_rate = (record.completed_jobs / total * 100.0) if total else 0.0
        failure_rate = (record.failed_jobs / total * 100.0) if total else 0.0
        retry_rate = (record.retry_events / total * 100.0) if total else 0.0
        score = completion_rate - failure_rate * 0.5 - min(25.0, retry_rate * 0.35)
        if record.result == "failed":
            score -= 20.0
        if bool(record.monitor_metrics.get("stalled", False)):
            score -= 10.0
        return round(max(0.0, min(100.0, score)), 1)

    def _comparable_history(
        self,
        record: BatchSessionRecord,
        history: Iterable[BatchSessionRecord],
        thresholds: GenerationPerformanceThresholds,
    ) -> list[BatchSessionRecord]:
        candidates = [
            item
            for item in history
            if item.session_id != record.session_id
            and item.result == "completed"
            and item.project_id == record.project_id
            and item.provider == record.provider
            and item.model == record.model
            and item.voice == record.voice
            and item.scope == record.scope
            and item.total_jobs > 0
        ]
        return sorted(candidates, key=lambda item: item.started_at, reverse=True)[
            : thresholds.baseline_window_size
        ]

    @staticmethod
    def _metrics(record: BatchSessionRecord) -> dict[str, float]:
        total = max(0, record.total_jobs)
        processed = max(0, record.completed_jobs + record.failed_jobs + record.skipped_jobs)
        active_seconds = max(0.0, record.active_seconds or record.elapsed_seconds)
        return {
            "completion_rate": (record.completed_jobs / total * 100.0) if total else 0.0,
            "failure_rate": (record.failed_jobs / total * 100.0) if total else 0.0,
            "seconds_per_job": (active_seconds / processed) if processed else 0.0,
            "files_per_minute": max(0.0, record.files_per_minute),
            "characters_per_minute": max(0.0, record.characters_per_minute),
            "retries_per_100_jobs": (record.retry_events / total * 100.0) if total else 0.0,
        }

    @staticmethod
    def _median(values: Iterable[float], *, positive_only: bool = False) -> float:
        available = [float(value) for value in values]
        if positive_only:
            available = [value for value in available if value > 0.0]
        return round(float(statistics.median(available)), 6) if available else 0.0

    @staticmethod
    def _ratio_delta(current: float, baseline: float) -> float:
        if baseline <= 0:
            return 0.0
        return (current - baseline) / baseline

    @staticmethod
    def _throughput_delta(deltas: dict[str, float]) -> float:
        character_delta = deltas["characters_per_minute_ratio"]
        return character_delta if character_delta else deltas["files_per_minute_ratio"]

    def _thresholds_for(self, project_id: int | None) -> GenerationPerformanceThresholds:
        if self.policy_service is None:
            return self.thresholds
        return self.policy_service.budget_for(project_id).thresholds

    @staticmethod
    def _classify_completion(
        delta: float,
        warnings: list[str],
        criticals: list[str],
        thresholds: GenerationPerformanceThresholds,
    ) -> None:
        drop = -delta
        if drop >= thresholds.completion_drop_critical:
            criticals.append(f"Completion rate dropped {drop:.1f} percentage points")
        elif drop >= thresholds.completion_drop_warning:
            warnings.append(f"Completion rate dropped {drop:.1f} percentage points")

    @staticmethod
    def _classify_failure(
        delta: float,
        warnings: list[str],
        criticals: list[str],
        thresholds: GenerationPerformanceThresholds,
    ) -> None:
        if delta >= thresholds.failure_rate_increase_critical:
            criticals.append(f"Failure rate increased {delta:.1f} percentage points")
        elif delta >= thresholds.failure_rate_increase_warning:
            warnings.append(f"Failure rate increased {delta:.1f} percentage points")

    @staticmethod
    def _classify_throughput(
        delta: float,
        warnings: list[str],
        criticals: list[str],
        thresholds: GenerationPerformanceThresholds,
    ) -> None:
        drop = -delta
        if drop >= thresholds.throughput_drop_critical:
            criticals.append(f"Throughput dropped {drop * 100.0:.1f}%")
        elif drop >= thresholds.throughput_drop_warning:
            warnings.append(f"Throughput dropped {drop * 100.0:.1f}%")

    @staticmethod
    def _classify_elapsed(
        delta: float,
        warnings: list[str],
        criticals: list[str],
        thresholds: GenerationPerformanceThresholds,
    ) -> None:
        if delta >= thresholds.elapsed_increase_critical:
            criticals.append(f"Seconds per job increased {delta * 100.0:.1f}%")
        elif delta >= thresholds.elapsed_increase_warning:
            warnings.append(f"Seconds per job increased {delta * 100.0:.1f}%")

    @staticmethod
    def _classify_retry(
        delta: float,
        warnings: list[str],
        criticals: list[str],
        thresholds: GenerationPerformanceThresholds,
    ) -> None:
        if delta >= thresholds.retry_rate_increase_critical:
            criticals.append(f"Retry rate increased {delta:.1f} per 100 jobs")
        elif delta >= thresholds.retry_rate_increase_warning:
            warnings.append(f"Retry rate increased {delta:.1f} per 100 jobs")
