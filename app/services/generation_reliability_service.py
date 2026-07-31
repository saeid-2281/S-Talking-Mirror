from __future__ import annotations

import csv
import hashlib
import json
import re
import uuid
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from app.models.generation_incident import GenerationIncident
from app.models.generation_reliability import (
    GenerationProviderReliability,
    GenerationReliabilityDashboard,
    GenerationReliabilitySnapshot,
    GenerationSloPolicy,
)
from app.models.product_events import ActivityEvent, BatchSessionRecord, NotificationRecord
from app.repositories.product_event_repository import ProductEventRepository


class GenerationReliabilityService:
    """Calculate SLO health, error budgets, burn rates, and reliability trends."""

    def __init__(
        self,
        repository: ProductEventRepository,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def default_policy(project_id: int | None = None) -> GenerationSloPolicy:
        return GenerationSloPolicy(project_id=project_id)

    def get_policy(self, project_id: int | None) -> GenerationSloPolicy:
        if project_id is not None:
            project_policy = self.repository.get_reliability_slo_policy(project_id)
            if project_policy is not None:
                return project_policy
        global_policy = self.repository.get_reliability_slo_policy(None)
        if global_policy is not None:
            return replace(global_policy, project_id=project_id)
        return self.default_policy(project_id)

    def save_policy(self, policy: GenerationSloPolicy) -> GenerationSloPolicy:
        normalized = replace(
            policy,
            window_days=max(1, min(3650, int(policy.window_days))),
            minimum_sessions=max(1, int(policy.minimum_sessions)),
            target_job_success_rate=self._percentage(policy.target_job_success_rate),
            max_retry_rate=self._percentage(policy.max_retry_rate),
            max_mtta_minutes=max(1.0, float(policy.max_mtta_minutes)),
            max_mttr_minutes=max(1.0, float(policy.max_mttr_minutes)),
            max_incident_recurrence_rate=self._percentage(
                policy.max_incident_recurrence_rate
            ),
            min_runbook_success_rate=self._percentage(policy.min_runbook_success_rate),
            min_corrective_action_completion_rate=self._percentage(
                policy.min_corrective_action_completion_rate
            ),
            warning_burn_rate=max(0.1, float(policy.warning_burn_rate)),
            critical_burn_rate=max(
                max(0.1, float(policy.warning_burn_rate)),
                float(policy.critical_burn_rate),
            ),
            alert_cooldown_minutes=max(0, int(policy.alert_cooldown_minutes)),
            updated_at=self._now().isoformat(),
        )
        self.repository.save_reliability_slo_policy(normalized)
        return normalized

    def dashboard(
        self,
        *,
        project_id: int | None = None,
        now: datetime | None = None,
        history_limit: int = 60,
    ) -> GenerationReliabilityDashboard:
        current = self._aware(now or self._now())
        policy = self.get_policy(project_id)
        period_end = current
        period_start = period_end - timedelta(days=policy.window_days)
        previous_start = period_start - timedelta(days=policy.window_days)

        snapshot = self._calculate(
            project_id=project_id,
            policy=policy,
            period_start=period_start,
            period_end=period_end,
            created_at=current,
        )
        previous = self._calculate(
            project_id=project_id,
            policy=policy,
            period_start=previous_start,
            period_end=period_start,
            created_at=current,
            snapshot_id=f"preview-previous-{uuid.uuid4().hex}",
        )
        trend = self._trend(snapshot, previous)
        snapshot = replace(snapshot, trend=trend)
        history = tuple(
            self.repository.list_reliability_snapshots(
                project_id=project_id,
                limit=history_limit,
            )
        )
        return GenerationReliabilityDashboard(
            policy=policy,
            snapshot=snapshot,
            previous_snapshot=previous,
            history=history,
            target_status=self.target_status(snapshot, policy),
        )

    def evaluate_and_persist(
        self,
        *,
        project_id: int | None = None,
        now: datetime | None = None,
    ) -> GenerationReliabilitySnapshot:
        dashboard = self.dashboard(project_id=project_id, now=now)
        snapshot = dashboard.snapshot
        self.repository.add_reliability_snapshot(snapshot)
        if snapshot.state not in {"warning", "critical"}:
            return snapshot
        if not snapshot.alert_fingerprint:
            return snapshot

        current = self._parse(snapshot.created_at)
        since = current - timedelta(minutes=dashboard.policy.alert_cooldown_minutes)
        if self.repository.has_recent_reliability_alert(
            snapshot.alert_fingerprint,
            since.isoformat(),
        ):
            return snapshot

        severity = "error" if snapshot.state == "critical" else "warning"
        title = (
            "Critical reliability SLO burn"
            if snapshot.state == "critical"
            else "Reliability SLO warning"
        )
        message = "; ".join(snapshot.reasons) or "Reliability targets are not being met."
        notification = NotificationRecord(
            notification_id=uuid.uuid4().hex,
            severity=severity,
            title=title,
            message=message,
            created_at=snapshot.created_at,
            action_label="Open Reliability Dashboard",
            action_payload="generation-reliability-dashboard",
        )
        self.repository.add_notification(notification)
        self.repository.attach_reliability_snapshot_notification(
            snapshot.snapshot_id,
            notification.notification_id,
        )
        self.repository.add_activity(
            ActivityEvent(
                event_id=uuid.uuid4().hex,
                project_id=project_id,
                category="generation-reliability",
                title=title,
                message=message,
                created_at=snapshot.created_at,
                metadata={
                    "snapshot_id": snapshot.snapshot_id,
                    "state": snapshot.state,
                    "burn_rate": snapshot.burn_rate,
                    "error_budget_remaining_percent": (
                        snapshot.error_budget_remaining_percent
                    ),
                    "alert_fingerprint": snapshot.alert_fingerprint,
                    "notification_id": notification.notification_id,
                },
            )
        )
        return replace(snapshot, alert_notification_id=notification.notification_id)

    def recalculate(
        self,
        *,
        project_id: int | None = None,
        now: datetime | None = None,
    ) -> GenerationReliabilitySnapshot:
        return self.evaluate_and_persist(project_id=project_id, now=now)

    @staticmethod
    def target_status(
        snapshot: GenerationReliabilitySnapshot,
        policy: GenerationSloPolicy,
    ) -> dict[str, str]:
        if not policy.enabled:
            return {"overall": "disabled"}
        status = {
            "overall": snapshot.state,
            "job_success_rate": (
                "met"
                if snapshot.job_success_rate >= policy.target_job_success_rate
                else "breached"
            ),
            "retry_rate": (
                "met" if snapshot.retry_rate <= policy.max_retry_rate else "breached"
            ),
            "mtta": (
                "no_data"
                if snapshot.acknowledged_incident_count == 0
                else "met"
                if snapshot.mtta_minutes <= policy.max_mtta_minutes
                else "breached"
            ),
            "mttr": (
                "no_data"
                if snapshot.resolved_incident_count == 0
                else "met"
                if snapshot.mttr_minutes <= policy.max_mttr_minutes
                else "breached"
            ),
            "incident_recurrence": (
                "no_data"
                if snapshot.incident_count == 0
                else "met"
                if GenerationReliabilityService._rate(
                    snapshot.recurring_incident_count,
                    snapshot.incident_count,
                )
                <= policy.max_incident_recurrence_rate
                else "breached"
            ),
            "runbook_success": (
                "no_data"
                if snapshot.runbook_execution_count == 0
                else "met"
                if snapshot.runbook_success_rate >= policy.min_runbook_success_rate
                else "breached"
            ),
            "corrective_actions": (
                "no_data"
                if snapshot.corrective_action_count == 0
                else "met"
                if snapshot.corrective_action_completion_rate
                >= policy.min_corrective_action_completion_rate
                else "breached"
            ),
        }
        return status

    @staticmethod
    def export(
        dashboard: GenerationReliabilityDashboard,
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-")
        safe_name = safe_name or "reliability"
        json_path = directory / f"generation-reliability-{safe_name}-{stamp}.json"
        csv_path = directory / f"generation-reliability-{safe_name}-{stamp}.csv"

        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project": project_name,
            "policy": asdict(dashboard.policy),
            "snapshot": asdict(dashboard.snapshot),
            "previous_snapshot": (
                asdict(dashboard.previous_snapshot)
                if dashboard.previous_snapshot is not None
                else None
            ),
            "target_status": dashboard.target_status,
            "history": [asdict(item) for item in dashboard.history],
        }
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        row = asdict(dashboard.snapshot)
        row["reasons_json"] = json.dumps(row.pop("reasons"), ensure_ascii=False)
        row["provider_metrics_json"] = json.dumps(
            row.pop("provider_metrics"),
            ensure_ascii=False,
        )
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        return json_path, csv_path

    def _calculate(
        self,
        *,
        project_id: int | None,
        policy: GenerationSloPolicy,
        period_start: datetime,
        period_end: datetime,
        created_at: datetime,
        snapshot_id: str | None = None,
    ) -> GenerationReliabilitySnapshot:
        sessions = self.repository.list_batch_sessions_between(
            project_id=project_id,
            started_at=period_start.isoformat(),
            finished_before=period_end.isoformat(),
        )
        all_incidents = self.repository.list_incidents(
            project_id=project_id,
            limit=100000,
        )
        incidents = [
            item
            for item in all_incidents
            if period_start <= self._parse(item.updated_at or item.created_at) < period_end
        ]
        total_jobs = sum(max(0, item.total_jobs) for item in sessions)
        completed_jobs = sum(max(0, item.completed_jobs) for item in sessions)
        failed_jobs = sum(max(0, item.failed_jobs) for item in sessions)
        retry_events = sum(max(0, item.retry_events) for item in sessions)
        success_rate = self._rate(completed_jobs, total_jobs)
        failure_rate = self._rate(failed_jobs, total_jobs)
        retry_rate = self._rate(retry_events, total_jobs)
        throughput = self._average(
            item.files_per_minute for item in sessions if item.files_per_minute > 0
        )
        health = self._average(
            item.health_score for item in sessions if item.health_score > 0
        )

        mtta_values: list[float] = []
        mttr_values: list[float] = []
        for incident in incidents:
            created = self._parse(incident.created_at)
            if incident.acknowledged_at:
                mtta_values.append(
                    max(0.0, (self._parse(incident.acknowledged_at) - created).total_seconds())
                    / 60.0
                )
            if incident.resolved_at:
                mttr_values.append(
                    max(0.0, (self._parse(incident.resolved_at) - created).total_seconds())
                    / 60.0
                )
        mtta = self._average(mtta_values)
        mttr = self._average(mttr_values)

        runbook_total, runbook_completed = self._runbook_metrics(
            all_incidents,
            period_start,
            period_end,
        )
        runbook_success = self._rate(runbook_completed, runbook_total)
        actions = self.repository.list_incident_action_items(
            project_id=project_id,
            limit=100000,
        )
        current_actions = [
            item
            for item in actions
            if period_start <= self._parse(item.created_at) < period_end
            and item.status != "cancelled"
        ]
        completed_actions = sum(item.status == "completed" for item in current_actions)
        action_completion = self._rate(completed_actions, len(current_actions))

        allowed_failure_rate = max(0.0, 100.0 - policy.target_job_success_rate)
        allowed_jobs = total_jobs * allowed_failure_rate / 100.0
        consumed_jobs = float(failed_jobs)
        if allowed_jobs <= 0.0:
            remaining = 100.0 if consumed_jobs <= 0.0 else 0.0
            burn_rate = 0.0 if consumed_jobs <= 0.0 else 999.0
        else:
            remaining = max(0.0, min(100.0, (allowed_jobs - consumed_jobs) / allowed_jobs * 100.0))
            burn_rate = failure_rate / allowed_failure_rate

        recurrence_rate = self._rate(
            sum(item.occurrence_count > 1 for item in incidents),
            len(incidents),
        )
        reasons: list[str] = []
        breach_codes: list[str] = []
        critical = False
        if not policy.enabled:
            state = "disabled"
        elif len(sessions) < policy.minimum_sessions:
            state = "insufficient_data"
            reasons.append(
                f"Only {len(sessions)} session(s) are available; "
                f"{policy.minimum_sessions} are required."
            )
        else:
            if success_rate < policy.target_job_success_rate:
                breach_codes.append("job_success_rate")
                reasons.append(
                    f"Job success rate {success_rate:.2f}% is below the "
                    f"{policy.target_job_success_rate:.2f}% target."
                )
                critical = success_rate < policy.target_job_success_rate - 5.0
            if retry_rate > policy.max_retry_rate:
                breach_codes.append("retry_rate")
                reasons.append(
                    f"Retry rate {retry_rate:.2f}% exceeds the "
                    f"{policy.max_retry_rate:.2f}% limit."
                )
            if mtta_values and mtta > policy.max_mtta_minutes:
                breach_codes.append("mtta")
                reasons.append(
                    f"MTTA {mtta:.1f} min exceeds the "
                    f"{policy.max_mtta_minutes:.1f} min target."
                )
            if mttr_values and mttr > policy.max_mttr_minutes:
                breach_codes.append("mttr")
                reasons.append(
                    f"MTTR {mttr:.1f} min exceeds the "
                    f"{policy.max_mttr_minutes:.1f} min target."
                )
                critical = critical or mttr > policy.max_mttr_minutes * 2.0
            if incidents and recurrence_rate > policy.max_incident_recurrence_rate:
                breach_codes.append("incident_recurrence")
                reasons.append(
                    f"Incident recurrence {recurrence_rate:.2f}% exceeds the "
                    f"{policy.max_incident_recurrence_rate:.2f}% limit."
                )
            if runbook_total and runbook_success < policy.min_runbook_success_rate:
                breach_codes.append("runbook_success")
                reasons.append(
                    f"Runbook success {runbook_success:.2f}% is below the "
                    f"{policy.min_runbook_success_rate:.2f}% target."
                )
            if current_actions and action_completion < policy.min_corrective_action_completion_rate:
                breach_codes.append("corrective_actions")
                reasons.append(
                    f"Corrective-action completion {action_completion:.2f}% is below the "
                    f"{policy.min_corrective_action_completion_rate:.2f}% target."
                )
            if burn_rate >= policy.critical_burn_rate:
                breach_codes.append("critical_burn")
                reasons.append(
                    f"Error-budget burn rate {burn_rate:.2f}x exceeds the "
                    f"{policy.critical_burn_rate:.2f}x critical threshold."
                )
                critical = True
            elif burn_rate >= policy.warning_burn_rate:
                breach_codes.append("warning_burn")
                reasons.append(
                    f"Error-budget burn rate {burn_rate:.2f}x exceeds the "
                    f"{policy.warning_burn_rate:.2f}x warning threshold."
                )
            state = "critical" if critical else "warning" if reasons else "healthy"

        fingerprint = None
        if state in {"warning", "critical"}:
            raw = f"{project_id}|{state}|{'|'.join(sorted(set(breach_codes)))}"
            fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        return GenerationReliabilitySnapshot(
            snapshot_id=snapshot_id or uuid.uuid4().hex,
            project_id=project_id,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            created_at=created_at.isoformat(),
            state=state,
            session_count=len(sessions),
            total_jobs=total_jobs,
            completed_jobs=completed_jobs,
            failed_jobs=failed_jobs,
            retry_events=retry_events,
            job_success_rate=success_rate,
            failure_rate=failure_rate,
            retry_rate=retry_rate,
            average_files_per_minute=throughput,
            average_health_score=health,
            incident_count=len(incidents),
            recurring_incident_count=sum(item.occurrence_count > 1 for item in incidents),
            critical_incident_count=sum(item.severity == "critical" for item in incidents),
            acknowledged_incident_count=len(mtta_values),
            resolved_incident_count=len(mttr_values),
            mtta_minutes=mtta,
            mttr_minutes=mttr,
            runbook_execution_count=runbook_total,
            runbook_success_rate=runbook_success,
            corrective_action_count=len(current_actions),
            corrective_action_completion_rate=action_completion,
            error_budget_allowed_jobs=allowed_jobs,
            error_budget_consumed_jobs=consumed_jobs,
            error_budget_remaining_percent=remaining,
            burn_rate=burn_rate,
            reasons=tuple(dict.fromkeys(reasons)),
            provider_metrics=self._provider_metrics(sessions),
            alert_fingerprint=fingerprint,
        )

    def _runbook_metrics(
        self,
        incidents: Iterable[GenerationIncident],
        period_start: datetime,
        period_end: datetime,
    ) -> tuple[int, int]:
        total = 0
        completed = 0
        for incident in incidents:
            for item in self.repository.list_incident_remediations(
                incident.incident_id,
                limit=10000,
            ):
                started = self._parse(item.started_at)
                if period_start <= started < period_end and item.status != "active":
                    total += 1
                    completed += item.status == "completed"
            for item in self.repository.list_automated_remediations(
                incident.incident_id,
                limit=10000,
            ):
                started = self._parse(item.started_at)
                if (
                    period_start <= started < period_end
                    and not item.dry_run
                    and item.status != "running"
                ):
                    total += 1
                    completed += item.status == "completed"
        return total, completed

    @staticmethod
    def _provider_metrics(
        sessions: Iterable[BatchSessionRecord],
    ) -> tuple[GenerationProviderReliability, ...]:
        grouped: dict[str, list[BatchSessionRecord]] = defaultdict(list)
        for session in sessions:
            grouped[session.provider or "unknown"].append(session)
        result: list[GenerationProviderReliability] = []
        for provider, items in sorted(grouped.items()):
            total = sum(max(0, item.total_jobs) for item in items)
            completed = sum(max(0, item.completed_jobs) for item in items)
            failed = sum(max(0, item.failed_jobs) for item in items)
            retries = sum(max(0, item.retry_events) for item in items)
            result.append(
                GenerationProviderReliability(
                    provider=provider,
                    session_count=len(items),
                    total_jobs=total,
                    completed_jobs=completed,
                    failed_jobs=failed,
                    retry_events=retries,
                    job_success_rate=GenerationReliabilityService._rate(completed, total),
                    failure_rate=GenerationReliabilityService._rate(failed, total),
                    retry_rate=GenerationReliabilityService._rate(retries, total),
                    average_files_per_minute=GenerationReliabilityService._average(
                        item.files_per_minute
                        for item in items
                        if item.files_per_minute > 0
                    ),
                    average_health_score=GenerationReliabilityService._average(
                        item.health_score for item in items if item.health_score > 0
                    ),
                )
            )
        return tuple(result)

    @staticmethod
    def _trend(
        current: GenerationReliabilitySnapshot,
        previous: GenerationReliabilitySnapshot,
    ) -> str:
        if not current.session_count or not previous.session_count:
            return "unknown"
        score = (
            current.job_success_rate
            - previous.job_success_rate
            - (current.failure_rate - previous.failure_rate)
            - 0.25 * (current.retry_rate - previous.retry_rate)
        )
        if score >= 0.5:
            return "improving"
        if score <= -0.5:
            return "degrading"
        return "stable"

    def _now(self) -> datetime:
        return self._aware(self._now_factory())

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    @classmethod
    def _parse(cls, value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return cls._aware(parsed)

    @staticmethod
    def _rate(numerator: int | float, denominator: int | float) -> float:
        return float(numerator) / float(denominator) * 100.0 if denominator else 0.0

    @staticmethod
    def _average(values: Iterable[float]) -> float:
        items = [float(value) for value in values]
        return sum(items) / len(items) if items else 0.0

    @staticmethod
    def _percentage(value: float) -> float:
        return max(0.0, min(100.0, float(value)))
