from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models.generation_performance import GenerationPerformanceAnalysis
from app.models.product_events import ActivityEvent, BatchSessionRecord, NotificationRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.activity_timeline_service import ActivityTimelineService
from app.services.generation_incident_service import GenerationIncidentService
from app.services.generation_cost_capacity_service import GenerationCostCapacityService
from app.services.generation_problem_service import GenerationProblemService
from app.services.generation_remediation_automation_service import (
    GenerationRemediationAutomationService,
)
from app.services.generation_performance_policy_service import (
    GenerationPerformancePolicyService,
)
from app.services.generation_performance_service import GenerationPerformanceService
from app.services.generation_reliability_service import GenerationReliabilityService
from app.services.notification_center_service import NotificationCenterService


class ProductActivityService:
    def __init__(
        self,
        repository: ProductEventRepository,
        notification_center: NotificationCenterService | None = None,
        activity_timeline: ActivityTimelineService | None = None,
        performance_service: GenerationPerformanceService | None = None,
        performance_policy_service: GenerationPerformancePolicyService | None = None,
        incident_service: GenerationIncidentService | None = None,
        problem_service: GenerationProblemService | None = None,
        automation_service: GenerationRemediationAutomationService | None = None,
        reliability_service: GenerationReliabilityService | None = None,
        cost_capacity_service: GenerationCostCapacityService | None = None,
    ) -> None:
        self.repository = repository
        self.notification_center = notification_center
        self.activity_timeline = activity_timeline
        self.performance_service = performance_service
        self.performance_policy_service = performance_policy_service
        self.incident_service = incident_service
        self.problem_service = problem_service
        self.automation_service = automation_service
        self.reliability_service = reliability_service
        self.cost_capacity_service = cost_capacity_service

    def notify(
        self,
        severity: str,
        title: str,
        message: str,
        *,
        action_label: str | None = None,
        action_payload: str | None = None,
    ) -> NotificationRecord:
        record = NotificationRecord(
            notification_id=uuid.uuid4().hex,
            severity=severity,
            title=title,
            message=message,
            created_at=self._now(),
            action_label=action_label,
            action_payload=action_payload,
        )
        if self.notification_center is not None:
            return self.notification_center.publish(record)
        self.repository.add_notification(record)
        return record

    def activity(
        self,
        category: str,
        title: str,
        message: str,
        *,
        project_id: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ActivityEvent:
        event = ActivityEvent(
            event_id=uuid.uuid4().hex,
            project_id=project_id,
            category=category,
            title=title,
            message=message,
            created_at=self._now(),
            metadata=metadata or {},
        )
        if self.activity_timeline is not None:
            return self.activity_timeline.record(event)
        self.repository.add_activity(event)
        return event

    def record_batch(
        self,
        record: BatchSessionRecord,
    ) -> GenerationPerformanceAnalysis | None:
        self.repository.add_batch_session(record)
        if self.cost_capacity_service is not None:
            self.cost_capacity_service.record_session(record)
        if self.performance_service is None:
            self._update_reliability(record.project_id)
            return None
        analysis = self.performance_service.analyze_and_persist(record)
        if analysis.severity not in {"warning", "critical"}:
            self._update_reliability(record.project_id)
            return analysis

        decision = None
        if self.performance_policy_service is not None:
            decision = self.performance_policy_service.decide_and_persist(record, analysis)

        incident = None
        if self.incident_service is not None:
            incident = self.incident_service.record_regression(record, analysis, decision)
            if incident is not None:
                is_new = incident.occurrence_count == 1
                problem_match = None
                if self.problem_service is not None:
                    problem_match = self.problem_service.match_incident(
                        incident.incident_id,
                        auto_link=True,
                    )
                self.activity(
                    "generation-incident",
                    "Generation incident opened" if is_new else "Incident occurrence added",
                    incident.summary,
                    project_id=record.project_id,
                    metadata={
                        "incident_id": incident.incident_id,
                        "session_id": record.session_id,
                        "status": incident.status,
                        "occurrence_count": incident.occurrence_count,
                        "alert_fingerprint": incident.alert_fingerprint,
                    },
                )
                if self.automation_service is not None:
                    trigger = (
                        "known_problem_recurrence"
                        if problem_match is not None
                        else "incident_opened"
                    )
                    try:
                        self.automation_service.auto_run_for_incident(
                            incident.incident_id,
                            trigger=trigger,
                        )
                    except ValueError as exc:
                        self.activity(
                            "generation-automation",
                            "Automatic remediation was not started",
                            str(exc),
                            project_id=record.project_id,
                            metadata={
                                "incident_id": incident.incident_id,
                                "trigger": trigger,
                            },
                        )

        if decision is not None:
            if not decision.notify:
                self.activity(
                    "generation-performance-alert",
                    "Generation alert not emitted",
                    decision.reason or f"Alert state: {decision.state}",
                    project_id=record.project_id,
                    metadata={
                        "session_id": record.session_id,
                        "health_score": analysis.health_score,
                        "severity": analysis.severity,
                        "alert_state": decision.state,
                        "alert_fingerprint": decision.fingerprint,
                    },
                )
                self._update_reliability(record.project_id)
                return analysis

        severity = "error" if analysis.severity == "critical" else "warning"
        title = (
            "Critical generation regression"
            if analysis.severity == "critical"
            else "Generation performance warning"
        )
        message = "; ".join(analysis.reasons) or "Performance is below the rolling baseline."
        notification = self.notify(
            severity,
            title,
            message,
            action_label="Open Incident Center" if incident is not None else "Open generation history",
            action_payload="generation-incident-center" if incident is not None else "generation-history",
        )
        if decision is not None and self.performance_policy_service is not None:
            self.performance_policy_service.attach_notification(
                record.session_id,
                notification.notification_id,
            )
        self.activity(
            "generation-performance",
            title,
            message,
            project_id=record.project_id,
            metadata={
                "session_id": record.session_id,
                "health_score": analysis.health_score,
                "severity": analysis.severity,
                "baseline_session_id": analysis.baseline_session_id,
                "reasons": list(analysis.reasons),
                "alert_state": decision.state if decision is not None else "open",
                "alert_fingerprint": decision.fingerprint if decision is not None else None,
                "notification_id": notification.notification_id,
            },
        )
        self._update_reliability(record.project_id)
        return analysis

    def _update_reliability(self, project_id: int | None) -> None:
        if self.reliability_service is not None:
            self.reliability_service.evaluate_and_persist(project_id=project_id)
        if self.cost_capacity_service is not None:
            self.cost_capacity_service.evaluate_and_persist(project_id=project_id)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
