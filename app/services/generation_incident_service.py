from __future__ import annotations

import csv
import json
import re
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.generation_automation import GenerationAutomationAction
from app.models.generation_incident import (
    GenerationIncident,
    GenerationIncidentActionItem,
    GenerationIncidentRemediation,
    GenerationIncidentRunbook,
    GenerationIncidentReview,
    GenerationIncidentSlaPolicy,
    GenerationIncidentSummary,
    GenerationIncidentUpdate,
    GenerationRemediationStep,
)
from app.models.generation_performance import (
    GenerationAlertDecision,
    GenerationPerformanceAnalysis,
)
from app.models.product_events import ActivityEvent, BatchSessionRecord, NotificationRecord
from app.repositories.product_event_repository import ProductEventRepository


class GenerationIncidentService:
    """Group regressions into incidents and manage ownership, SLA, and escalation."""

    VALID_STATUSES = {"open", "acknowledged", "resolved", "dismissed"}
    ACTIVE_STATUSES = {"open", "acknowledged"}
    VALID_SLA_STATES = {
        "not_configured",
        "on_track",
        "response_overdue",
        "resolution_overdue",
        "met",
        "breached",
    }
    VALID_RUNBOOK_SEVERITIES = {"any", "critical", "warning"}
    VALID_REMEDIATION_STATUSES = {"active", "completed", "failed", "cancelled"}
    VALID_STEP_STATUSES = {"pending", "in_progress", "completed", "skipped", "failed"}
    VALID_REVIEW_STATUSES = {"draft", "completed"}
    VALID_ROOT_CAUSE_CATEGORIES = {
        "provider",
        "network",
        "configuration",
        "authentication",
        "quota",
        "data",
        "validation",
        "filesystem",
        "application",
        "unknown",
    }
    VALID_ACTION_STATUSES = {"open", "in_progress", "completed", "cancelled"}
    VALID_ACTION_PRIORITIES = {"p1", "p2", "p3", "p4"}
    VALID_AUTOMATION_TRIGGERS = {
        "manual",
        "incident_opened",
        "known_problem_recurrence",
    }
    VALID_AUTOMATION_ACTIONS = {
        "record_workaround",
        "evaluate_sla",
        "acknowledge_incident",
        "retry_transient_jobs",
        "reset_interrupted_jobs",
    }

    def __init__(
        self,
        repository: ProductEventRepository,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    def record_regression(
        self,
        record: BatchSessionRecord,
        analysis: GenerationPerformanceAnalysis,
        decision: GenerationAlertDecision | None,
    ) -> GenerationIncident | None:
        if analysis.severity != "critical":
            return None
        fingerprint = (decision.fingerprint if decision is not None else None) or record.alert_fingerprint
        if not fingerprint:
            return None

        existing = self.repository.find_active_incident(
            project_id=record.project_id,
            alert_fingerprint=fingerprint,
        )
        now = self._now()
        now_text = now.isoformat()
        summary = "; ".join(analysis.reasons) or "Critical generation regression."
        if existing is not None:
            session_ids = tuple(dict.fromkeys((*existing.session_ids, record.session_id)))
            reopened = existing.status == "acknowledged"
            status = "open" if reopened else existing.status
            response_due_at = existing.response_due_at
            resolution_due_at = existing.resolution_due_at
            sla_state = existing.sla_state
            escalation_level = existing.escalation_level
            escalated_at = existing.escalated_at
            last_notification_level = existing.last_sla_notification_level
            if reopened or not response_due_at or not resolution_due_at:
                response_due_at, resolution_due_at, sla_state = self._deadlines(
                    record.project_id,
                    analysis.severity,
                    now,
                )
                escalation_level = 0
                escalated_at = None
                last_notification_level = 0
            incident = replace(
                existing,
                severity="critical",
                status=status,
                summary=summary,
                latest_session_id=record.session_id,
                occurrence_count=len(session_ids),
                session_ids=session_ids,
                updated_at=now_text,
                acknowledged_at=None if status == "open" else existing.acknowledged_at,
                response_due_at=response_due_at,
                resolution_due_at=resolution_due_at,
                sla_state=sla_state,
                escalation_level=escalation_level,
                escalated_at=escalated_at,
                last_sla_notification_level=last_notification_level,
            )
            self.repository.add_incident(incident)
            if status != existing.status:
                self.repository.update_incident_status(
                    (incident.incident_id,),
                    status=status,
                    updated_at=now_text,
                )
            self.repository.link_batch_incident(record.session_id, incident.incident_id, status)
            self._add_update(
                incident.incident_id,
                "reopened" if reopened else "occurrence",
                (
                    f"Incident reopened by session {record.session_id}."
                    if reopened
                    else f"Occurrence added from session {record.session_id}."
                ),
                metadata={
                    "session_id": record.session_id,
                    "occurrence_count": incident.occurrence_count,
                },
                created_at=now_text,
            )
            return incident

        if decision is not None and decision.state != "open":
            return None

        response_due_at, resolution_due_at, sla_state = self._deadlines(
            record.project_id,
            analysis.severity,
            now,
        )
        incident = GenerationIncident(
            incident_id=uuid.uuid4().hex,
            project_id=record.project_id,
            alert_fingerprint=fingerprint,
            severity="critical",
            status="open",
            title="Critical generation performance incident",
            summary=summary,
            first_session_id=record.session_id,
            latest_session_id=record.session_id,
            occurrence_count=1,
            session_ids=(record.session_id,),
            created_at=now_text,
            updated_at=now_text,
            priority="p1",
            response_due_at=response_due_at,
            resolution_due_at=resolution_due_at,
            sla_state=sla_state,
        )
        self.repository.add_incident(incident)
        self.repository.link_batch_incident(record.session_id, incident.incident_id, incident.status)
        self._add_update(
            incident.incident_id,
            "created",
            f"Incident created from session {record.session_id}.",
            metadata={"session_id": record.session_id, "severity": analysis.severity},
            created_at=now_text,
        )
        return incident

    def list_incidents(
        self,
        *,
        project_id: int | None = None,
        status: str | None = None,
        severity: str | None = None,
        search: str = "",
        limit: int = 500,
        evaluate_sla: bool = False,
    ) -> list[GenerationIncident]:
        if evaluate_sla:
            self.evaluate_sla(project_id=project_id)
        incidents = self.repository.list_incidents(
            project_id=project_id,
            status=status,
            severity=severity,
            limit=limit,
        )
        query = search.strip().casefold()
        if not query:
            return incidents
        return [
            incident
            for incident in incidents
            if query
            in " ".join(
                (
                    incident.incident_id,
                    incident.alert_fingerprint,
                    incident.title,
                    incident.summary,
                    incident.first_session_id,
                    incident.latest_session_id,
                    incident.resolution_note or "",
                    incident.assigned_to or "",
                    incident.priority,
                    incident.sla_state,
                )
            ).casefold()
        ]

    def get_sla_policy(self, project_id: int | None) -> GenerationIncidentSlaPolicy:
        if project_id is not None:
            project_policy = self.repository.get_incident_sla_policy(project_id)
            if project_policy is not None:
                return project_policy
        global_policy = self.repository.get_incident_sla_policy(None)
        if global_policy is not None:
            return global_policy
        return GenerationIncidentSlaPolicy()

    def save_sla_policy(
        self,
        policy: GenerationIncidentSlaPolicy,
    ) -> GenerationIncidentSlaPolicy:
        normalized = replace(
            policy,
            critical_response_minutes=max(1, int(policy.critical_response_minutes)),
            critical_resolution_minutes=max(1, int(policy.critical_resolution_minutes)),
            warning_response_minutes=max(1, int(policy.warning_response_minutes)),
            warning_resolution_minutes=max(1, int(policy.warning_resolution_minutes)),
            updated_at=self._now().isoformat(),
        )
        self.repository.save_incident_sla_policy(normalized)
        self._backfill_sla(normalized.project_id)
        return normalized

    def assign(
        self,
        incident_ids: Iterable[str],
        assigned_to: str,
        *,
        actor: str | None = None,
    ) -> int:
        ids = self._ids(incident_ids)
        if not ids:
            return 0
        owner = assigned_to.strip() or None
        now = self._now().isoformat()
        incidents = self._existing(ids)
        count = self.repository.update_incident_assignment(
            tuple(item.incident_id for item in incidents),
            assigned_to=owner,
            updated_at=now,
        )
        for incident in incidents:
            message = (
                f"Incident assigned to {owner}."
                if owner is not None
                else "Incident assignment cleared."
            )
            self._add_update(
                incident.incident_id,
                "assignment",
                message,
                actor=actor,
                metadata={"assigned_to": owner or ""},
                created_at=now,
            )
            self._activity(incident, "Generation incident assignment changed", message, now)
        return count

    def add_note(
        self,
        incident_id: str,
        message: str,
        *,
        actor: str | None = None,
    ) -> GenerationIncidentUpdate | None:
        incident = self.repository.get_incident(incident_id)
        text = message.strip()
        if incident is None or not text:
            return None
        update = self._add_update(
            incident_id,
            "note",
            text,
            actor=actor,
        )
        self._activity(incident, "Generation incident note added", text, update.created_at)
        return update

    def list_updates(
        self,
        incident_id: str,
        *,
        limit: int = 200,
    ) -> list[GenerationIncidentUpdate]:
        return self.repository.list_incident_updates(incident_id, limit=limit)

    def acknowledge(self, incident_ids: Iterable[str]) -> int:
        return self._transition(incident_ids, status="acknowledged")

    def resolve(self, incident_ids: Iterable[str], note: str = "") -> int:
        return self._transition(incident_ids, status="resolved", note=note)

    def dismiss(self, incident_ids: Iterable[str], note: str = "") -> int:
        return self._transition(incident_ids, status="dismissed", note=note)

    def reopen(self, incident_ids: Iterable[str]) -> int:
        return self._transition(incident_ids, status="open")

    def evaluate_sla(
        self,
        *,
        project_id: int | None = None,
        now: datetime | None = None,
    ) -> list[GenerationIncident]:
        current = self._aware(now or self._now())
        incidents = self.repository.list_incidents(project_id=project_id, limit=5000)
        changed: list[GenerationIncident] = []
        for incident in incidents:
            if incident.status not in self.ACTIVE_STATUSES:
                continue
            policy = self.get_sla_policy(incident.project_id)
            response_due = self._parse(incident.response_due_at)
            resolution_due = self._parse(incident.resolution_due_at)
            if policy.enabled and (response_due is None or resolution_due is None):
                created = self._parse(incident.created_at) or current
                response_text, resolution_text, _state = self._deadlines(
                    incident.project_id,
                    incident.severity,
                    created,
                )
                response_due = self._parse(response_text)
                resolution_due = self._parse(resolution_text)
            state, level = self._sla_state(
                incident.status,
                current,
                response_due,
                resolution_due,
                policy.enabled,
            )
            response_text = response_due.isoformat() if response_due is not None else None
            resolution_text = resolution_due.isoformat() if resolution_due is not None else None
            escalated_at = incident.escalated_at
            last_notification_level = incident.last_sla_notification_level
            newly_escalated = level > incident.escalation_level
            if newly_escalated:
                escalated_at = current.isoformat()
            should_notify = level > last_notification_level
            if should_notify:
                self._publish_sla_notification(incident, state, level, current)
                last_notification_level = level
            needs_update = any(
                (
                    incident.response_due_at != response_text,
                    incident.resolution_due_at != resolution_text,
                    incident.sla_state != state,
                    incident.escalation_level != level,
                    incident.escalated_at != escalated_at,
                    incident.last_sla_notification_level != last_notification_level,
                )
            )
            if not needs_update:
                continue
            self.repository.update_incident_sla(
                incident.incident_id,
                response_due_at=response_text,
                resolution_due_at=resolution_text,
                sla_state=state,
                escalation_level=level,
                escalated_at=escalated_at,
                last_sla_notification_level=last_notification_level,
                updated_at=current.isoformat(),
            )
            updated = self.repository.get_incident(incident.incident_id)
            if updated is not None:
                changed.append(updated)
            if newly_escalated:
                message = self._sla_message(incident, state, level)
                self._add_update(
                    incident.incident_id,
                    "escalation",
                    message,
                    metadata={"sla_state": state, "escalation_level": level},
                    created_at=current.isoformat(),
                )
                self._activity(
                    incident,
                    f"Generation incident escalated to level {level}",
                    message,
                    current.isoformat(),
                    extra={"sla_state": state, "escalation_level": level},
                )
        return changed

    def _transition(
        self,
        incident_ids: Iterable[str],
        *,
        status: str,
        note: str = "",
    ) -> int:
        ids = self._ids(incident_ids)
        if not ids or status not in self.VALID_STATUSES:
            return 0
        incidents = self._existing(ids)
        if not incidents:
            return 0
        now = self._now()
        now_text = now.isoformat()
        acknowledged_at = now_text if status in {"acknowledged", "resolved"} else None
        resolved_at = now_text if status in {"resolved", "dismissed"} else None
        count = self.repository.update_incident_status(
            tuple(incident.incident_id for incident in incidents),
            status=status,
            updated_at=now_text,
            acknowledged_at=acknowledged_at,
            resolved_at=resolved_at,
            resolution_note=note.strip() or None,
        )
        for incident in incidents:
            if status == "open":
                response_due_at, resolution_due_at, sla_state = self._deadlines(
                    incident.project_id,
                    incident.severity,
                    now,
                )
                escalation_level = 0
                escalated_at = None
                last_notification_level = 0
            elif status in {"resolved", "dismissed"}:
                response_due_at = incident.response_due_at
                resolution_due_at = incident.resolution_due_at
                deadline = self._parse(resolution_due_at)
                sla_state = (
                    "not_configured"
                    if deadline is None
                    else ("met" if now <= deadline else "breached")
                )
                escalation_level = incident.escalation_level
                escalated_at = incident.escalated_at
                last_notification_level = incident.last_sla_notification_level
            else:
                response_due_at = incident.response_due_at
                resolution_due_at = incident.resolution_due_at
                policy = self.get_sla_policy(incident.project_id)
                sla_state, escalation_level = self._sla_state(
                    status,
                    now,
                    self._parse(response_due_at),
                    self._parse(resolution_due_at),
                    policy.enabled,
                )
                escalated_at = incident.escalated_at
                last_notification_level = incident.last_sla_notification_level
            self.repository.update_incident_sla(
                incident.incident_id,
                response_due_at=response_due_at,
                resolution_due_at=resolution_due_at,
                sla_state=sla_state,
                escalation_level=escalation_level,
                escalated_at=escalated_at,
                last_sla_notification_level=last_notification_level,
                updated_at=now_text,
            )
            title = (
                "Generation incident reopened"
                if status == "open"
                else f"Generation incident {status}"
            )
            message = (
                f"Incident {incident.incident_id} changed to {status}."
                + (f" {note.strip()}" if note.strip() else "")
            )
            self._activity(
                incident,
                title,
                message,
                now_text,
                extra={"resolution_note": note.strip()},
            )
            self._add_update(
                incident.incident_id,
                "status",
                message,
                metadata={"status": status, "resolution_note": note.strip()},
                created_at=now_text,
            )
        return count

    def ensure_default_runbooks(self) -> list[GenerationIncidentRunbook]:
        existing = {
            item.runbook_id: item
            for item in self.repository.list_incident_runbooks(include_global=False)
        }
        defaults = (
            GenerationIncidentRunbook(
                runbook_id="default-provider-recovery",
                project_id=None,
                name="Provider and network recovery",
                description="Verify provider health and safely resume interrupted jobs.",
                severity_filter="critical",
                fingerprint_pattern=r"provider|network|server|rate|quota|timeout",
                steps=(
                    "Confirm provider status and account readiness.",
                    "Review error category, fingerprint, and affected sessions.",
                    "Validate API profile, model, voice, and quota settings.",
                    "Retry one transient failed job as a controlled probe.",
                    "Resume eligible failed jobs and monitor throughput.",
                ),
                automation_trigger="known_problem_recurrence",
                automation_actions=(
                    GenerationAutomationAction(
                        action_type="record_workaround",
                        title="Record the known-problem workaround",
                    ),
                    GenerationAutomationAction(
                        action_type="reset_interrupted_jobs",
                        title="Reset interrupted jobs",
                        rollback_instruction="Reapply the previous queue snapshot if required.",
                    ),
                    GenerationAutomationAction(
                        action_type="retry_transient_jobs",
                        title="Schedule transient failures for retry",
                        parameters={"max_retries": 4},
                        rollback_instruction="Cancel pending retries before generation restarts.",
                    ),
                ),
                rollback_instructions=(
                    "Stop generation, cancel pending retries, and restore the latest queue snapshot."
                ),
            ),
            GenerationIncidentRunbook(
                runbook_id="default-output-recovery",
                project_id=None,
                name="Output and filesystem recovery",
                description="Repair output-path, permission, or storage failures.",
                severity_filter="any",
                fingerprint_pattern=r"output|file|filesystem|disk|permission|path",
                steps=(
                    "Confirm the output directory exists and is writable.",
                    "Check free disk space and conflicting output files.",
                    "Review project output settings and filename policy.",
                    "Generate one controlled test file.",
                    "Resume pending jobs after output validation passes.",
                ),
                automation_actions=(
                    GenerationAutomationAction(
                        action_type="reset_interrupted_jobs",
                        title="Reset interrupted jobs",
                    ),
                    GenerationAutomationAction(
                        action_type="evaluate_sla",
                        title="Refresh incident SLA state",
                    ),
                ),
                rollback_instructions="Restore the queue snapshot before resuming generation.",
            ),
            GenerationIncidentRunbook(
                runbook_id="default-critical-triage",
                project_id=None,
                name="General critical incident triage",
                description="A safe fallback workflow for critical generation regressions.",
                severity_filter="critical",
                steps=(
                    "Acknowledge and assign the incident.",
                    "Review the latest session, failures, retries, and performance deltas.",
                    "Identify whether the failure is transient or permanent.",
                    "Apply the smallest reversible corrective action.",
                    "Validate recovery and document the resolution.",
                ),
                automation_actions=(
                    GenerationAutomationAction(
                        action_type="acknowledge_incident",
                        title="Acknowledge the incident",
                        rollback_instruction="Reopen the incident if acknowledgement was premature.",
                    ),
                    GenerationAutomationAction(
                        action_type="evaluate_sla",
                        title="Refresh SLA and escalation state",
                    ),
                ),
                rollback_instructions="Reopen the incident and restore its previous assignment.",
            ),
        )
        saved: list[GenerationIncidentRunbook] = []
        for default in defaults:
            current = existing.get(default.runbook_id)
            if current is None:
                saved.append(self.save_runbook(default))
                continue
            if not current.automation_actions:
                current = replace(
                    current,
                    automation_trigger=default.automation_trigger,
                    automation_actions=default.automation_actions,
                    dry_run_only=default.dry_run_only,
                    max_auto_runs=default.max_auto_runs,
                    cooldown_minutes=default.cooldown_minutes,
                    rollback_instructions=default.rollback_instructions,
                )
                current = self.save_runbook(current)
            saved.append(current)
        saved.extend(
            item for key, item in existing.items() if key not in {d.runbook_id for d in defaults}
        )
        return saved

    def save_runbook(
        self,
        runbook: GenerationIncidentRunbook,
    ) -> GenerationIncidentRunbook:
        name = runbook.name.strip()
        if not name:
            raise ValueError("Runbook name is required.")
        severity = runbook.severity_filter.strip().lower() or "any"
        if severity not in self.VALID_RUNBOOK_SEVERITIES:
            raise ValueError(f"Unsupported runbook severity: {severity}")
        pattern = runbook.fingerprint_pattern.strip()
        if pattern:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"Invalid fingerprint pattern: {exc}") from exc
        steps = tuple(step.strip() for step in runbook.steps if step.strip())
        if not steps:
            raise ValueError("Runbook must contain at least one remediation step.")
        automation_trigger = runbook.automation_trigger.strip().lower() or "manual"
        if automation_trigger not in self.VALID_AUTOMATION_TRIGGERS:
            raise ValueError(f"Unsupported automation trigger: {automation_trigger}")
        automation_actions: list[GenerationAutomationAction] = []
        for action in runbook.automation_actions:
            action_type = action.action_type.strip().lower()
            if action_type not in self.VALID_AUTOMATION_ACTIONS:
                raise ValueError(f"Unsupported automation action: {action.action_type}")
            automation_actions.append(
                replace(
                    action,
                    action_type=action_type,
                    title=(
                        action.title.strip()
                        or action_type.replace("_", " ").title()
                    ),
                    parameters={
                        str(key): value for key, value in action.parameters.items()
                    },
                    rollback_instruction=action.rollback_instruction.strip(),
                )
            )
        if runbook.automation_enabled and not automation_actions:
            raise ValueError(
                "Automation-enabled runbooks require at least one allowlisted action."
            )
        max_auto_runs = max(1, min(20, int(runbook.max_auto_runs)))
        cooldown_minutes = max(0, min(10080, int(runbook.cooldown_minutes)))
        now = self._now().isoformat()
        normalized = replace(
            runbook,
            runbook_id=runbook.runbook_id.strip() or uuid.uuid4().hex,
            name=name,
            description=runbook.description.strip(),
            severity_filter=severity,
            fingerprint_pattern=pattern,
            steps=steps,
            automation_trigger=automation_trigger,
            automation_actions=tuple(automation_actions),
            max_auto_runs=max_auto_runs,
            cooldown_minutes=cooldown_minutes,
            rollback_instructions=runbook.rollback_instructions.strip(),
            created_at=runbook.created_at or now,
            updated_at=now,
        )
        self.repository.save_incident_runbook(normalized)
        return normalized

    def delete_runbook(self, runbook_id: str) -> int:
        return self.repository.delete_incident_runbook(runbook_id.strip())

    def list_runbooks(
        self,
        *,
        project_id: int | None = None,
        include_global: bool = True,
        enabled_only: bool = False,
    ) -> list[GenerationIncidentRunbook]:
        return self.repository.list_incident_runbooks(
            project_id=project_id,
            include_global=include_global,
            enabled_only=enabled_only,
        )

    def recommend_runbooks(self, incident_id: str) -> list[GenerationIncidentRunbook]:
        incident = self.repository.get_incident(incident_id)
        if incident is None:
            return []
        runbooks = self.list_runbooks(
            project_id=incident.project_id,
            include_global=True,
            enabled_only=True,
        )
        searchable = " ".join(
            (incident.alert_fingerprint, incident.title, incident.summary)
        )

        def score(runbook: GenerationIncidentRunbook) -> tuple[int, str]:
            value = 0
            if runbook.project_id == incident.project_id and incident.project_id is not None:
                value += 4
            if runbook.severity_filter == incident.severity:
                value += 3
            elif runbook.severity_filter == "any":
                value += 1
            if runbook.fingerprint_pattern:
                try:
                    if re.search(runbook.fingerprint_pattern, searchable, re.IGNORECASE):
                        value += 6
                    else:
                        value -= 5
                except re.error:
                    value -= 5
            return value, runbook.name.casefold()

        candidates = [
            runbook
            for runbook in runbooks
            if runbook.severity_filter in {"any", incident.severity}
        ]
        return sorted(candidates, key=lambda item: (-score(item)[0], score(item)[1]))

    def start_remediation(
        self,
        incident_id: str,
        runbook_id: str,
        *,
        actor: str | None = None,
    ) -> GenerationIncidentRemediation:
        incident = self.repository.get_incident(incident_id)
        if incident is None:
            raise ValueError("Incident was not found.")
        if incident.status not in self.ACTIVE_STATUSES:
            raise ValueError("Runbooks can only start for active incidents.")
        active = self.repository.find_active_incident_remediation(incident_id)
        if active is not None:
            return active
        runbook = self.repository.get_incident_runbook(runbook_id)
        if runbook is None or not runbook.enabled:
            raise ValueError("Runbook is unavailable or disabled.")
        if runbook.project_id not in {None, incident.project_id}:
            raise ValueError("Runbook belongs to a different project.")
        now = self._now().isoformat()
        remediation = GenerationIncidentRemediation(
            remediation_id=uuid.uuid4().hex,
            incident_id=incident_id,
            runbook_id=runbook.runbook_id,
            runbook_name=runbook.name,
            status="active",
            steps=tuple(
                GenerationRemediationStep(position=index, title=title)
                for index, title in enumerate(runbook.steps)
            ),
            actor=self._actor(actor),
            started_at=now,
            updated_at=now,
        )
        self.repository.save_incident_remediation(remediation)
        message = f"Runbook '{runbook.name}' started with {len(remediation.steps)} step(s)."
        self._add_update(
            incident_id,
            "runbook_started",
            message,
            actor=actor,
            metadata={
                "remediation_id": remediation.remediation_id,
                "runbook_id": runbook.runbook_id,
            },
            created_at=now,
        )
        self._activity(incident, "Generation remediation started", message, now)
        return remediation

    def update_remediation_step(
        self,
        remediation_id: str,
        position: int,
        status: str,
        *,
        note: str = "",
        actor: str | None = None,
    ) -> GenerationIncidentRemediation:
        normalized_status = status.strip().lower()
        if normalized_status not in self.VALID_STEP_STATUSES:
            raise ValueError(f"Unsupported remediation step status: {status}")
        remediation = self.repository.get_incident_remediation(remediation_id)
        if remediation is None:
            raise ValueError("Remediation execution was not found.")
        if remediation.status != "active":
            raise ValueError("Only an active remediation can be updated.")
        if position < 0 or position >= len(remediation.steps):
            raise IndexError("Remediation step position is out of range.")
        now = self._now().isoformat()
        steps = list(remediation.steps)
        current = steps[position]
        terminal = normalized_status in {"completed", "skipped", "failed"}
        steps[position] = replace(
            current,
            status=normalized_status,
            note=note.strip(),
            actor=self._actor(actor),
            completed_at=now if terminal else None,
        )
        if normalized_status == "failed":
            remediation_status = "failed"
            completed_at = now
        elif all(step.status in {"completed", "skipped"} for step in steps):
            remediation_status = "completed"
            completed_at = now
        else:
            remediation_status = "active"
            completed_at = None
        updated = replace(
            remediation,
            status=remediation_status,
            steps=tuple(steps),
            actor=self._actor(actor) or remediation.actor,
            updated_at=now,
            completed_at=completed_at,
        )
        self.repository.save_incident_remediation(updated)
        incident = self.repository.get_incident(remediation.incident_id)
        message = (
            f"Runbook step {position + 1} '{current.title}' changed to "
            f"{normalized_status}."
        )
        self._add_update(
            remediation.incident_id,
            "runbook_step",
            message,
            actor=actor,
            metadata={
                "remediation_id": remediation_id,
                "position": position,
                "status": normalized_status,
                "note": note.strip(),
            },
            created_at=now,
        )
        if incident is not None:
            self._activity(incident, "Generation remediation step updated", message, now)
        if remediation_status in {"completed", "failed"}:
            self._record_remediation_completion(updated, actor=actor)
        return updated

    def cancel_remediation(
        self,
        remediation_id: str,
        *,
        note: str = "",
        actor: str | None = None,
    ) -> GenerationIncidentRemediation:
        remediation = self.repository.get_incident_remediation(remediation_id)
        if remediation is None:
            raise ValueError("Remediation execution was not found.")
        if remediation.status != "active":
            return remediation
        now = self._now().isoformat()
        updated = replace(
            remediation,
            status="cancelled",
            actor=self._actor(actor) or remediation.actor,
            updated_at=now,
            completed_at=now,
        )
        self.repository.save_incident_remediation(updated)
        message = "Runbook execution cancelled."
        if note.strip():
            message += f" {note.strip()}"
        self._add_update(
            remediation.incident_id,
            "runbook_cancelled",
            message,
            actor=actor,
            metadata={"remediation_id": remediation_id},
            created_at=now,
        )
        incident = self.repository.get_incident(remediation.incident_id)
        if incident is not None:
            self._activity(incident, "Generation remediation cancelled", message, now)
        return updated

    def resume_remediation(
        self,
        remediation_id: str,
        *,
        actor: str | None = None,
    ) -> GenerationIncidentRemediation:
        remediation = self.repository.get_incident_remediation(remediation_id)
        if remediation is None:
            raise ValueError("Remediation execution was not found.")
        if remediation.status not in {"failed", "cancelled"}:
            return remediation
        now = self._now().isoformat()
        steps = tuple(
            replace(step, status="pending", completed_at=None)
            if step.status == "failed"
            else step
            for step in remediation.steps
        )
        updated = replace(
            remediation,
            status="active",
            steps=steps,
            actor=self._actor(actor) or remediation.actor,
            updated_at=now,
            completed_at=None,
        )
        self.repository.save_incident_remediation(updated)
        message = f"Runbook '{remediation.runbook_name}' resumed."
        self._add_update(
            remediation.incident_id,
            "runbook_resumed",
            message,
            actor=actor,
            metadata={"remediation_id": remediation_id},
            created_at=now,
        )
        incident = self.repository.get_incident(remediation.incident_id)
        if incident is not None:
            self._activity(incident, "Generation remediation resumed", message, now)
        return updated

    def list_remediations(
        self,
        incident_id: str,
        *,
        limit: int = 100,
    ) -> list[GenerationIncidentRemediation]:
        return self.repository.list_incident_remediations(incident_id, limit=limit)

    def active_remediation(
        self,
        incident_id: str,
    ) -> GenerationIncidentRemediation | None:
        return self.repository.find_active_incident_remediation(incident_id)

    def get_or_create_review(
        self,
        incident_id: str,
        *,
        actor: str | None = None,
    ) -> GenerationIncidentReview:
        existing = self.repository.get_incident_review(incident_id)
        if existing is not None:
            return existing
        incident = self.repository.get_incident(incident_id)
        if incident is None:
            raise ValueError("Incident was not found.")
        now = self._now().isoformat()
        remediations = self.list_remediations(incident_id, limit=20)
        completed = [
            item.runbook_name for item in remediations if item.status == "completed"
        ]
        resolution = incident.resolution_note or (
            f"Completed remediation: {', '.join(completed)}" if completed else ""
        )
        review = GenerationIncidentReview(
            review_id=uuid.uuid4().hex,
            incident_id=incident_id,
            impact_summary=(
                f"{max(1, incident.occurrence_count)} generation session(s) were linked "
                f"to this {incident.severity} incident."
            ),
            root_cause_category=self._infer_root_cause_category(incident),
            resolution_summary=resolution,
            reviewer=self._actor(actor) or incident.assigned_to,
            created_at=now,
            updated_at=now,
        )
        self.repository.save_incident_review(review)
        self._add_update(
            incident_id,
            "review_created",
            "Post-incident review created.",
            actor=actor,
            metadata={"review_id": review.review_id},
            created_at=now,
        )
        self._activity(
            incident,
            "Post-incident review created",
            f"Review {review.review_id} was created.",
            now,
            extra={"review_id": review.review_id},
        )
        return review

    def save_review(
        self,
        review: GenerationIncidentReview,
        *,
        complete: bool = False,
        actor: str | None = None,
    ) -> GenerationIncidentReview:
        incident = self.repository.get_incident(review.incident_id)
        if incident is None:
            raise ValueError("Incident was not found.")
        current = self.repository.get_incident_review(review.incident_id)
        if current is not None and current.review_id != review.review_id:
            raise ValueError("Incident already has a different review.")
        category = review.root_cause_category.strip().lower() or "unknown"
        if category not in self.VALID_ROOT_CAUSE_CATEGORIES:
            raise ValueError("Invalid root-cause category.")
        requested_status = review.status.strip().lower() or "draft"
        if requested_status not in self.VALID_REVIEW_STATUSES:
            raise ValueError("Invalid review status.")
        complete = complete or requested_status == "completed"
        status = "completed" if complete else "draft"
        if complete:
            if incident.status not in {"resolved", "dismissed"}:
                raise ValueError("Resolve or dismiss the incident before completing its review.")
            required = {
                "impact summary": review.impact_summary.strip(),
                "root cause": review.root_cause.strip(),
                "resolution summary": review.resolution_summary.strip(),
                "lessons learned": review.lessons_learned.strip(),
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"Complete the following fields: {', '.join(missing)}.")
        now = self._now().isoformat()
        created_at = review.created_at or (current.created_at if current else now)
        completed_at = (
            now
            if status == "completed" and not (current and current.completed_at)
            else (current.completed_at if status == "completed" and current else None)
        )
        normalized = replace(
            review,
            status=status,
            impact_summary=review.impact_summary.strip(),
            root_cause_category=category,
            root_cause=review.root_cause.strip(),
            contributing_factors=tuple(
                dict.fromkeys(value.strip() for value in review.contributing_factors if value.strip())
            ),
            detection_gap=review.detection_gap.strip(),
            resolution_summary=review.resolution_summary.strip(),
            lessons_learned=review.lessons_learned.strip(),
            reviewer=self._actor(review.reviewer) or self._actor(actor),
            created_at=created_at,
            updated_at=now,
            completed_at=completed_at,
        )
        self.repository.save_incident_review(normalized)
        kind = "review_completed" if status == "completed" else "review_saved"
        message = (
            "Post-incident review completed."
            if status == "completed"
            else "Post-incident review draft saved."
        )
        self._add_update(
            incident.incident_id,
            kind,
            message,
            actor=actor or normalized.reviewer,
            metadata={
                "review_id": normalized.review_id,
                "root_cause_category": normalized.root_cause_category,
            },
            created_at=now,
        )
        self._activity(
            incident,
            "Post-incident review completed" if status == "completed" else "Post-incident review saved",
            message,
            now,
            extra={"review_id": normalized.review_id, "review_status": status},
        )
        return normalized

    def get_review(self, incident_id: str) -> GenerationIncidentReview | None:
        return self.repository.get_incident_review(incident_id)

    def list_action_items(
        self,
        incident_id: str,
    ) -> list[GenerationIncidentActionItem]:
        return self.repository.list_incident_action_items(incident_id=incident_id)

    def add_action_item(
        self,
        incident_id: str,
        title: str,
        *,
        owner: str | None = None,
        due_at: str | None = None,
        priority: str = "p2",
        note: str = "",
        actor: str | None = None,
    ) -> GenerationIncidentActionItem:
        incident = self.repository.get_incident(incident_id)
        if incident is None:
            raise ValueError("Incident was not found.")
        review = self.get_or_create_review(incident_id, actor=actor)
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Action item title is required.")
        normalized_priority = priority.strip().lower() or "p2"
        if normalized_priority not in self.VALID_ACTION_PRIORITIES:
            raise ValueError("Invalid action-item priority.")
        normalized_due = self._normalize_optional_datetime(due_at)
        now = self._now().isoformat()
        action = GenerationIncidentActionItem(
            action_id=uuid.uuid4().hex,
            review_id=review.review_id,
            incident_id=incident_id,
            title=clean_title,
            priority=normalized_priority,
            owner=self._actor(owner),
            due_at=normalized_due,
            note=note.strip(),
            created_at=now,
            problem_id=incident.problem_id,
            updated_at=now,
        )
        self.repository.save_incident_action_item(action)
        self._add_update(
            incident_id,
            "review_action_created",
            f"Corrective action created: {action.title}",
            actor=actor,
            metadata={"action_id": action.action_id, "priority": action.priority},
            created_at=now,
        )
        self._activity(
            incident,
            "Corrective action created",
            action.title,
            now,
            extra={"action_id": action.action_id, "priority": action.priority},
        )
        return action

    def update_action_item(
        self,
        action_id: str,
        *,
        status: str | None = None,
        title: str | None = None,
        owner: str | None = None,
        due_at: str | None = None,
        priority: str | None = None,
        note: str | None = None,
        actor: str | None = None,
    ) -> GenerationIncidentActionItem:
        action = self.repository.get_incident_action_item(action_id)
        if action is None:
            raise ValueError("Action item was not found.")
        incident = self.repository.get_incident(action.incident_id)
        if incident is None:
            raise ValueError("Incident was not found.")
        normalized_status = status.strip().lower() if status is not None else action.status
        if normalized_status not in self.VALID_ACTION_STATUSES:
            raise ValueError("Invalid action-item status.")
        normalized_priority = priority.strip().lower() if priority is not None else action.priority
        if normalized_priority not in self.VALID_ACTION_PRIORITIES:
            raise ValueError("Invalid action-item priority.")
        clean_title = title.strip() if title is not None else action.title
        if not clean_title:
            raise ValueError("Action item title is required.")
        now = self._now().isoformat()
        completed_at = (
            now
            if normalized_status == "completed" and action.status != "completed"
            else (action.completed_at if normalized_status == "completed" else None)
        )
        updated = replace(
            action,
            title=clean_title,
            status=normalized_status,
            priority=normalized_priority,
            owner=self._actor(owner) if owner is not None else action.owner,
            due_at=self._normalize_optional_datetime(due_at) if due_at is not None else action.due_at,
            note=note.strip() if note is not None else action.note,
            updated_at=now,
            completed_at=completed_at,
            overdue_notified_at=(
                None
                if normalized_status in {"completed", "cancelled"} or due_at is not None
                else action.overdue_notified_at
            ),
        )
        self.repository.save_incident_action_item(updated)
        self._add_update(
            action.incident_id,
            "review_action_updated",
            f"Corrective action '{updated.title}' changed to {updated.status}.",
            actor=actor,
            metadata={"action_id": action.action_id, "status": updated.status},
            created_at=now,
        )
        self._activity(
            incident,
            "Corrective action updated",
            f"{updated.title}: {updated.status.replace('_', ' ')}",
            now,
            extra={"action_id": action.action_id, "action_status": updated.status},
        )
        return updated

    def delete_action_item(self, action_id: str, *, actor: str | None = None) -> int:
        action = self.repository.get_incident_action_item(action_id)
        if action is None:
            return 0
        incident = self.repository.get_incident(action.incident_id)
        count = self.repository.delete_incident_action_item(action_id)
        if count and incident is not None:
            now = self._now().isoformat()
            self._add_update(
                incident.incident_id,
                "review_action_deleted",
                f"Corrective action deleted: {action.title}",
                actor=actor,
                metadata={"action_id": action_id},
                created_at=now,
            )
            self._activity(
                incident,
                "Corrective action deleted",
                action.title,
                now,
                extra={"action_id": action_id},
            )
        return count

    def evaluate_action_items(
        self,
        *,
        project_id: int | None = None,
        now: datetime | None = None,
    ) -> list[GenerationIncidentActionItem]:
        current = self._aware(now or self._now())
        actions = self.repository.list_incident_action_items(
            project_id=project_id,
            limit=5000,
        )
        overdue: list[GenerationIncidentActionItem] = []
        for action in actions:
            if action.status not in {"open", "in_progress"}:
                continue
            due = self._parse(action.due_at)
            if due is None or current <= due:
                continue
            overdue.append(action)
            if action.overdue_notified_at:
                continue
            incident = self.repository.get_incident(action.incident_id)
            if incident is None:
                continue
            notified = replace(
                action,
                updated_at=current.isoformat(),
                overdue_notified_at=current.isoformat(),
            )
            self.repository.save_incident_action_item(notified)
            owner = action.owner or "unassigned"
            self.repository.add_notification(
                NotificationRecord(
                    notification_id=uuid.uuid4().hex,
                    severity="warning",
                    title="Corrective action overdue",
                    message=(
                        f"Action '{action.title}' for incident {action.incident_id} "
                        f"is overdue (owner: {owner})."
                    ),
                    created_at=current.isoformat(),
                    action_label="Open Incident Center",
                    action_payload="generation-incident-center",
                )
            )
            self._add_update(
                action.incident_id,
                "review_action_overdue",
                f"Corrective action overdue: {action.title}",
                metadata={"action_id": action.action_id, "owner": owner},
                created_at=current.isoformat(),
            )
            self._activity(
                incident,
                "Corrective action overdue",
                action.title,
                current.isoformat(),
                extra={"action_id": action.action_id, "owner": owner},
            )
        return overdue

    @staticmethod
    def summary(incidents: Iterable[GenerationIncident]) -> GenerationIncidentSummary:
        records = list(incidents)
        statuses = Counter(incident.status for incident in records)
        severities = Counter(incident.severity for incident in records)
        sla_states = Counter(incident.sla_state for incident in records)
        projects = Counter(
            "global" if incident.project_id is None else str(incident.project_id)
            for incident in records
        )
        return GenerationIncidentSummary(
            total=len(records),
            open_count=statuses["open"],
            acknowledged_count=statuses["acknowledged"],
            resolved_count=statuses["resolved"],
            dismissed_count=statuses["dismissed"],
            critical_count=severities["critical"],
            warning_count=severities["warning"],
            total_occurrences=sum(max(1, incident.occurrence_count) for incident in records),
            unassigned_count=sum(
                1
                for incident in records
                if incident.status in GenerationIncidentService.ACTIVE_STATUSES
                and not incident.assigned_to
            ),
            response_overdue_count=sla_states["response_overdue"],
            resolution_overdue_count=sla_states["resolution_overdue"],
            escalated_count=sum(1 for incident in records if incident.escalation_level > 0),
            by_project=dict(sorted(projects.items())),
        )

    def export(
        self,
        incidents: Iterable[GenerationIncident],
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        records = list(incidents)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "incidents"
        json_path = directory / f"generation-incidents-{safe_name}-{stamp}.json"
        csv_path = directory / f"generation-incidents-{safe_name}-{stamp}.csv"
        payload_records: list[dict[str, object]] = []
        for incident in records:
            item = self._payload(incident)
            item["updates"] = [
                self._update_payload(update)
                for update in self.list_updates(incident.incident_id)
            ]
            item["remediations"] = [
                self._remediation_payload(remediation)
                for remediation in self.list_remediations(incident.incident_id)
            ]
            item["automated_remediations"] = [
                self._automated_remediation_payload(execution)
                for execution in self.repository.list_automated_remediations(
                    incident.incident_id
                )
            ]
            item["post_incident_review"] = self._review_payload(
                self.get_review(incident.incident_id)
            )
            item["corrective_actions"] = [
                self._action_payload(action)
                for action in self.list_action_items(incident.incident_id)
            ]
            payload_records.append(item)
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project": project_name,
            "summary": self.summary(records).__dict__,
            "incidents": payload_records,
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        fieldnames = [
            "incident_id",
            "project_id",
            "alert_fingerprint",
            "severity",
            "status",
            "priority",
            "assigned_to",
            "sla_state",
            "response_due_at",
            "resolution_due_at",
            "escalation_level",
            "escalated_at",
            "title",
            "summary",
            "first_session_id",
            "latest_session_id",
            "occurrence_count",
            "session_ids_json",
            "updates_json",
            "remediations_json",
            "automated_remediations_json",
            "post_incident_review_json",
            "corrective_actions_json",
            "created_at",
            "updated_at",
            "acknowledged_at",
            "resolved_at",
            "resolution_note",
            "problem_id",
            "problem_status",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for incident in records:
                row = self._payload(incident)
                row.pop("session_ids", None)
                row.pop("last_sla_notification_level", None)
                row["session_ids_json"] = json.dumps(
                    list(incident.session_ids),
                    ensure_ascii=False,
                )
                row["updates_json"] = json.dumps(
                    [
                        self._update_payload(update)
                        for update in self.list_updates(incident.incident_id)
                    ],
                    ensure_ascii=False,
                )
                row["remediations_json"] = json.dumps(
                    [
                        self._remediation_payload(remediation)
                        for remediation in self.list_remediations(incident.incident_id)
                    ],
                    ensure_ascii=False,
                )
                row["automated_remediations_json"] = json.dumps(
                    [
                        self._automated_remediation_payload(execution)
                        for execution in self.repository.list_automated_remediations(
                            incident.incident_id
                        )
                    ],
                    ensure_ascii=False,
                )
                row["post_incident_review_json"] = json.dumps(
                    self._review_payload(self.get_review(incident.incident_id)),
                    ensure_ascii=False,
                )
                row["corrective_actions_json"] = json.dumps(
                    [
                        self._action_payload(action)
                        for action in self.list_action_items(incident.incident_id)
                    ],
                    ensure_ascii=False,
                )
                writer.writerow(row)
        return json_path, csv_path

    def _backfill_sla(self, project_id: int | None) -> None:
        incidents = self.repository.list_incidents(project_id=project_id, limit=5000)
        for incident in incidents:
            if incident.status not in self.ACTIVE_STATUSES:
                continue
            created = self._parse(incident.created_at) or self._now()
            response_due_at, resolution_due_at, state = self._deadlines(
                incident.project_id,
                incident.severity,
                created,
            )
            self.repository.update_incident_sla(
                incident.incident_id,
                response_due_at=response_due_at,
                resolution_due_at=resolution_due_at,
                sla_state=state,
                escalation_level=0,
                escalated_at=None,
                last_sla_notification_level=0,
                updated_at=self._now().isoformat(),
            )

    def _deadlines(
        self,
        project_id: int | None,
        severity: str,
        start: datetime,
    ) -> tuple[str | None, str | None, str]:
        policy = self.get_sla_policy(project_id)
        if not policy.enabled:
            return None, None, "not_configured"
        if severity == "critical":
            response_minutes = policy.critical_response_minutes
            resolution_minutes = policy.critical_resolution_minutes
        else:
            response_minutes = policy.warning_response_minutes
            resolution_minutes = policy.warning_resolution_minutes
        aware_start = self._aware(start)
        return (
            (aware_start + timedelta(minutes=max(1, response_minutes))).isoformat(),
            (aware_start + timedelta(minutes=max(1, resolution_minutes))).isoformat(),
            "on_track",
        )

    @staticmethod
    def _sla_state(
        status: str,
        now: datetime,
        response_due: datetime | None,
        resolution_due: datetime | None,
        enabled: bool,
    ) -> tuple[str, int]:
        if not enabled or response_due is None or resolution_due is None:
            return "not_configured", 0
        if now > resolution_due:
            return "resolution_overdue", 2
        if status == "open" and now > response_due:
            return "response_overdue", 1
        return "on_track", 0

    def _publish_sla_notification(
        self,
        incident: GenerationIncident,
        state: str,
        level: int,
        now: datetime,
    ) -> None:
        title = (
            "Generation incident resolution overdue"
            if level >= 2
            else "Generation incident response overdue"
        )
        message = self._sla_message(incident, state, level)
        self.repository.add_notification(
            NotificationRecord(
                notification_id=uuid.uuid4().hex,
                severity="error" if level >= 2 else "warning",
                title=title,
                message=message,
                created_at=now.isoformat(),
                action_label="Open Incident Center",
                action_payload="generation-incident-center",
            )
        )

    @staticmethod
    def _sla_message(incident: GenerationIncident, state: str, level: int) -> str:
        owner = incident.assigned_to or "unassigned"
        return (
            f"Incident {incident.incident_id} is {state.replace('_', ' ')} "
            f"(escalation level {level}, owner: {owner})."
        )

    def _activity(
        self,
        incident: GenerationIncident,
        title: str,
        message: str,
        created_at: str,
        *,
        extra: dict[str, object] | None = None,
    ) -> None:
        metadata: dict[str, object] = {
            "incident_id": incident.incident_id,
            "status": incident.status,
            "occurrence_count": incident.occurrence_count,
            "latest_session_id": incident.latest_session_id,
            "assigned_to": incident.assigned_to or "",
            "sla_state": incident.sla_state,
            "escalation_level": incident.escalation_level,
        }
        if extra:
            metadata.update(extra)
        self.repository.add_activity(
            ActivityEvent(
                event_id=uuid.uuid4().hex,
                project_id=incident.project_id,
                category="generation-incident",
                title=title,
                message=message,
                created_at=created_at,
                metadata=metadata,
            )
        )

    def _add_update(
        self,
        incident_id: str,
        kind: str,
        message: str,
        *,
        actor: str | None = None,
        metadata: dict[str, object] | None = None,
        created_at: str | None = None,
    ) -> GenerationIncidentUpdate:
        update = GenerationIncidentUpdate(
            update_id=uuid.uuid4().hex,
            incident_id=incident_id,
            kind=kind,
            message=message,
            actor=actor.strip() if actor and actor.strip() else None,
            metadata=metadata or {},
            created_at=created_at or self._now().isoformat(),
        )
        self.repository.add_incident_update(update)
        return update

    def _existing(self, incident_ids: Iterable[str]) -> list[GenerationIncident]:
        return [
            incident
            for incident_id in incident_ids
            if (incident := self.repository.get_incident(incident_id)) is not None
        ]

    def _record_remediation_completion(
        self,
        remediation: GenerationIncidentRemediation,
        *,
        actor: str | None = None,
    ) -> None:
        now = remediation.updated_at or self._now().isoformat()
        message = (
            f"Runbook '{remediation.runbook_name}' {remediation.status} "
            f"({remediation.completed_steps}/{remediation.total_steps} steps complete)."
        )
        self._add_update(
            remediation.incident_id,
            f"runbook_{remediation.status}",
            message,
            actor=actor,
            metadata={
                "remediation_id": remediation.remediation_id,
                "status": remediation.status,
                "progress_percent": remediation.progress_percent,
            },
            created_at=now,
        )
        incident = self.repository.get_incident(remediation.incident_id)
        if incident is not None:
            self._activity(incident, "Generation remediation finished", message, now)

    @staticmethod
    def _actor(value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @staticmethod
    def _automated_remediation_payload(execution) -> dict[str, object]:
        return {
            "automation_id": execution.automation_id,
            "incident_id": execution.incident_id,
            "problem_id": execution.problem_id,
            "runbook_id": execution.runbook_id,
            "runbook_name": execution.runbook_name,
            "trigger": execution.trigger,
            "status": execution.status,
            "dry_run": execution.dry_run,
            "actor": execution.actor,
            "blocked_reason": execution.blocked_reason,
            "rollback_status": execution.rollback_status,
            "rollback_note": execution.rollback_note,
            "started_at": execution.started_at,
            "updated_at": execution.updated_at,
            "completed_at": execution.completed_at,
            "action_results": [
                {
                    "position": result.position,
                    "action_type": result.action_type,
                    "title": result.title,
                    "status": result.status,
                    "message": result.message,
                    "output": result.output,
                    "started_at": result.started_at,
                    "completed_at": result.completed_at,
                    "rollback_instruction": result.rollback_instruction,
                }
                for result in execution.action_results
            ],
        }

    @staticmethod
    def _remediation_payload(
        remediation: GenerationIncidentRemediation,
    ) -> dict[str, object]:
        return {
            "remediation_id": remediation.remediation_id,
            "incident_id": remediation.incident_id,
            "runbook_id": remediation.runbook_id,
            "runbook_name": remediation.runbook_name,
            "status": remediation.status,
            "progress_percent": remediation.progress_percent,
            "completed_steps": remediation.completed_steps,
            "total_steps": remediation.total_steps,
            "actor": remediation.actor,
            "started_at": remediation.started_at,
            "updated_at": remediation.updated_at,
            "completed_at": remediation.completed_at,
            "steps": [
                {
                    "position": step.position,
                    "title": step.title,
                    "status": step.status,
                    "note": step.note,
                    "actor": step.actor,
                    "completed_at": step.completed_at,
                }
                for step in remediation.steps
            ],
        }

    @staticmethod
    def _infer_root_cause_category(incident: GenerationIncident) -> str:
        text = " ".join(
            (incident.alert_fingerprint, incident.title, incident.summary)
        ).casefold()
        for category, tokens in (
            ("authentication", ("auth", "credential", "api key", "unauthorized")),
            ("quota", ("quota", "rate limit", "429", "billing")),
            ("network", ("network", "timeout", "connection", "dns")),
            ("filesystem", ("filesystem", "disk", "output", "permission", "path")),
            ("validation", ("validation", "invalid", "schema", "format")),
            ("configuration", ("configuration", "config", "profile", "setting")),
            ("data", ("csv", "input", "row", "data")),
            ("provider", ("provider", "server", "5xx", "service")),
            ("application", ("application", "exception", "crash", "bug")),
        ):
            if any(token in text for token in tokens):
                return category
        return "unknown"

    @classmethod
    def _normalize_optional_datetime(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        if not text:
            return None
        parsed = cls._parse(text)
        if parsed is None:
            raise ValueError("Date/time must be a valid ISO-8601 value.")
        return parsed.isoformat()

    @staticmethod
    def _review_payload(review: GenerationIncidentReview | None) -> dict[str, object] | None:
        if review is None:
            return None
        return {
            "review_id": review.review_id,
            "incident_id": review.incident_id,
            "status": review.status,
            "impact_summary": review.impact_summary,
            "root_cause_category": review.root_cause_category,
            "root_cause": review.root_cause,
            "contributing_factors": list(review.contributing_factors),
            "detection_gap": review.detection_gap,
            "resolution_summary": review.resolution_summary,
            "lessons_learned": review.lessons_learned,
            "reviewer": review.reviewer,
            "created_at": review.created_at,
            "updated_at": review.updated_at,
            "completed_at": review.completed_at,
        }

    @staticmethod
    def _action_payload(action: GenerationIncidentActionItem) -> dict[str, object]:
        return {
            "action_id": action.action_id,
            "review_id": action.review_id,
            "incident_id": action.incident_id,
            "title": action.title,
            "status": action.status,
            "priority": action.priority,
            "owner": action.owner,
            "due_at": action.due_at,
            "note": action.note,
            "created_at": action.created_at,
            "updated_at": action.updated_at,
            "completed_at": action.completed_at,
            "overdue_notified_at": action.overdue_notified_at,
            "problem_id": action.problem_id,
        }

    @staticmethod
    def _payload(incident: GenerationIncident) -> dict[str, object]:
        return {
            "incident_id": incident.incident_id,
            "project_id": incident.project_id,
            "alert_fingerprint": incident.alert_fingerprint,
            "severity": incident.severity,
            "status": incident.status,
            "priority": incident.priority,
            "assigned_to": incident.assigned_to,
            "sla_state": incident.sla_state,
            "response_due_at": incident.response_due_at,
            "resolution_due_at": incident.resolution_due_at,
            "escalation_level": incident.escalation_level,
            "escalated_at": incident.escalated_at,
            "last_sla_notification_level": incident.last_sla_notification_level,
            "title": incident.title,
            "summary": incident.summary,
            "first_session_id": incident.first_session_id,
            "latest_session_id": incident.latest_session_id,
            "occurrence_count": incident.occurrence_count,
            "session_ids": list(incident.session_ids),
            "created_at": incident.created_at,
            "updated_at": incident.updated_at,
            "acknowledged_at": incident.acknowledged_at,
            "resolved_at": incident.resolved_at,
            "resolution_note": incident.resolution_note,
            "problem_id": incident.problem_id,
            "problem_status": incident.problem_status,
        }

    @staticmethod
    def _update_payload(update: GenerationIncidentUpdate) -> dict[str, object]:
        return {
            "update_id": update.update_id,
            "incident_id": update.incident_id,
            "kind": update.kind,
            "actor": update.actor,
            "message": update.message,
            "metadata": update.metadata,
            "created_at": update.created_at,
        }

    @staticmethod
    def _ids(values: Iterable[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(value) for value in values if str(value).strip()))

    @staticmethod
    def _parse(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return GenerationIncidentService._aware(datetime.fromisoformat(value))
        except ValueError:
            return None

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    def _now(self) -> datetime:
        return self._aware(self._now_factory())
