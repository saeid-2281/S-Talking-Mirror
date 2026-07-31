from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.models.domain import JobStatus
from app.models.generation_automation import (
    GenerationAutomatedRemediation,
    GenerationAutomationAction,
    GenerationAutomationActionResult,
    GenerationAutomationPolicy,
)
from app.models.generation_incident import (
    GenerationIncident,
    GenerationIncidentRunbook,
    GenerationIncidentUpdate,
)
from app.models.product_events import ActivityEvent, NotificationRecord
from app.repositories.job_repository import JobRepository
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_incident_service import GenerationIncidentService
from app.services.generation_problem_service import GenerationProblemService
from app.services.queue_service import QueueService


class GenerationRemediationAutomationService:
    """Execute only explicitly allowlisted, internal remediation actions."""

    ACTION_RISKS = {
        "record_workaround": "safe",
        "evaluate_sla": "safe",
        "acknowledge_incident": "mutating",
        "retry_transient_jobs": "mutating",
        "reset_interrupted_jobs": "mutating",
    }
    VALID_TRIGGERS = {"manual", "incident_opened", "known_problem_recurrence"}
    VALID_ROLLBACK_STATES = {
        "not_requested",
        "required",
        "completed",
        "failed",
    }
    TERMINAL_EXECUTION_STATES = {"completed", "failed", "blocked", "cancelled"}

    def __init__(
        self,
        repository: ProductEventRepository,
        incident_service: GenerationIncidentService,
        problem_service: GenerationProblemService | None = None,
        job_repository: JobRepository | None = None,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.incident_service = incident_service
        self.problem_service = problem_service
        self.job_repository = job_repository
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    @property
    def supported_actions(self) -> tuple[str, ...]:
        return tuple(sorted(self.ACTION_RISKS))

    def default_policy(self, project_id: int | None = None) -> GenerationAutomationPolicy:
        return GenerationAutomationPolicy(
            project_id=project_id,
            enabled=False,
            dry_run_default=True,
            allowed_actions=self.supported_actions,
            require_confirmation_for_mutating=True,
            allow_unattended_mutating=False,
            max_auto_runs_per_incident=2,
            cooldown_minutes=60,
        )

    def get_policy(self, project_id: int | None) -> GenerationAutomationPolicy:
        project_policy = self.repository.get_remediation_automation_policy(project_id)
        if project_policy is not None:
            return project_policy
        if project_id is not None:
            global_policy = self.repository.get_remediation_automation_policy(None)
            if global_policy is not None:
                return replace(global_policy, project_id=project_id)
        return self.default_policy(project_id)

    def save_policy(
        self,
        policy: GenerationAutomationPolicy,
    ) -> GenerationAutomationPolicy:
        allowed = tuple(dict.fromkeys(value.strip() for value in policy.allowed_actions if value.strip()))
        unknown = sorted(set(allowed) - set(self.supported_actions))
        if unknown:
            raise ValueError(f"Unsupported automation action(s): {', '.join(unknown)}")
        max_runs = int(policy.max_auto_runs_per_incident)
        cooldown = int(policy.cooldown_minutes)
        if max_runs < 1 or max_runs > 20:
            raise ValueError("Maximum automatic runs must be between 1 and 20.")
        if cooldown < 0 or cooldown > 10080:
            raise ValueError("Automation cooldown must be between 0 and 10080 minutes.")
        normalized = replace(
            policy,
            allowed_actions=allowed or self.supported_actions,
            max_auto_runs_per_incident=max_runs,
            cooldown_minutes=cooldown,
            updated_at=self._now().isoformat(),
        )
        self.repository.save_remediation_automation_policy(normalized)
        return normalized

    def validate_runbook(
        self,
        runbook: GenerationIncidentRunbook,
    ) -> GenerationIncidentRunbook:
        trigger = runbook.automation_trigger.strip().lower() or "manual"
        if trigger not in self.VALID_TRIGGERS:
            raise ValueError(f"Unsupported automation trigger: {trigger}")
        max_runs = int(runbook.max_auto_runs)
        cooldown = int(runbook.cooldown_minutes)
        if max_runs < 1 or max_runs > 20:
            raise ValueError("Runbook maximum automatic runs must be between 1 and 20.")
        if cooldown < 0 or cooldown > 10080:
            raise ValueError("Runbook cooldown must be between 0 and 10080 minutes.")
        actions: list[GenerationAutomationAction] = []
        for action in runbook.automation_actions:
            action_type = action.action_type.strip().lower()
            if action_type not in self.ACTION_RISKS:
                raise ValueError(f"Unsupported automation action: {action.action_type}")
            title = action.title.strip() or action_type.replace("_", " ").title()
            actions.append(
                replace(
                    action,
                    action_type=action_type,
                    title=title,
                    parameters={str(key): value for key, value in action.parameters.items()},
                    rollback_instruction=action.rollback_instruction.strip(),
                )
            )
        if runbook.automation_enabled and not actions:
            raise ValueError("Automation-enabled runbooks require at least one action.")
        return replace(
            runbook,
            automation_trigger=trigger,
            automation_actions=tuple(actions),
            max_auto_runs=max_runs,
            cooldown_minutes=cooldown,
            rollback_instructions=runbook.rollback_instructions.strip(),
        )

    def execute(
        self,
        incident_id: str,
        runbook_id: str,
        *,
        trigger: str = "manual",
        dry_run: bool | None = None,
        actor: str | None = None,
        confirmed: bool = False,
    ) -> GenerationAutomatedRemediation:
        trigger = trigger.strip().lower() or "manual"
        if trigger not in self.VALID_TRIGGERS:
            raise ValueError(f"Unsupported automation trigger: {trigger}")
        incident = self.repository.get_incident(incident_id)
        if incident is None:
            raise ValueError("Incident was not found.")
        if incident.status not in self.incident_service.ACTIVE_STATUSES:
            raise ValueError("Automated remediation can only run for active incidents.")
        runbook = self.repository.get_incident_runbook(runbook_id)
        if runbook is None or not runbook.enabled:
            raise ValueError("Runbook is unavailable or disabled.")
        runbook = self.validate_runbook(runbook)
        if not runbook.automation_enabled:
            raise ValueError("Automation is disabled for this runbook.")
        if runbook.project_id not in {None, incident.project_id}:
            raise ValueError("Runbook belongs to a different project.")
        if trigger != "manual" and runbook.automation_trigger != trigger:
            raise ValueError("Runbook does not allow this automatic trigger.")

        policy = self.get_policy(incident.project_id)
        requested_dry_run = policy.dry_run_default if dry_run is None else bool(dry_run)
        if runbook.dry_run_only and not requested_dry_run:
            raise ValueError("This runbook is restricted to Dry Run mode.")
        effective_dry_run = bool(runbook.dry_run_only or requested_dry_run)
        mutating = any(
            self.ACTION_RISKS[action.action_type] == "mutating"
            for action in runbook.automation_actions
        )
        if trigger != "manual" and mutating and not policy.allow_unattended_mutating:
            effective_dry_run = True
        if (
            not effective_dry_run
            and mutating
            and policy.require_confirmation_for_mutating
            and not confirmed
        ):
            raise ValueError("Live mutating remediation requires explicit confirmation.")

        blocked_reason = self._eligibility_reason(
            incident,
            runbook,
            policy,
            trigger=trigger,
            dry_run=effective_dry_run,
        )
        if blocked_reason:
            return self._blocked_execution(
                incident,
                runbook,
                trigger=trigger,
                dry_run=effective_dry_run,
                actor=actor,
                reason=blocked_reason,
            )
        if self.repository.find_running_automated_remediation(incident_id) is not None:
            raise ValueError("Another automated remediation is already running for this incident.")

        now = self._now().isoformat()
        execution = GenerationAutomatedRemediation(
            automation_id=uuid.uuid4().hex,
            incident_id=incident.incident_id,
            problem_id=incident.problem_id,
            runbook_id=runbook.runbook_id,
            runbook_name=runbook.name,
            trigger=trigger,
            status="running",
            dry_run=effective_dry_run,
            actor=self._actor(actor),
            started_at=now,
            updated_at=now,
        )
        self.repository.save_automated_remediation(execution)
        self._record_event(
            incident,
            execution,
            "Automated remediation started",
            (
                f"Dry Run started for '{runbook.name}'."
                if effective_dry_run
                else f"Live automation started for '{runbook.name}'."
            ),
            kind="automation_started",
        )

        results: list[GenerationAutomationActionResult] = []
        failed = False
        for position, action in enumerate(runbook.automation_actions):
            result = self._run_action(
                incident,
                action,
                position=position,
                dry_run=effective_dry_run,
                actor=actor,
            )
            results.append(result)
            if result.status == "failed":
                failed = True
                break
        completed_at = self._now().isoformat()
        status = "failed" if failed else "completed"
        rollback_status = "required" if failed and runbook.rollback_instructions else "not_requested"
        execution = replace(
            execution,
            status=status,
            action_results=tuple(results),
            rollback_status=rollback_status,
            rollback_note=runbook.rollback_instructions if rollback_status == "required" else "",
            updated_at=completed_at,
            completed_at=completed_at,
        )
        self.repository.save_automated_remediation(execution)
        message = (
            f"Automation failed after {len(results)} action(s)."
            if failed
            else f"Automation completed {len(results)} action(s)."
        )
        self._record_event(
            incident,
            execution,
            "Automated remediation failed" if failed else "Automated remediation completed",
            message,
            kind="automation_failed" if failed else "automation_completed",
        )
        if failed:
            self.repository.add_notification(
                NotificationRecord(
                    notification_id=uuid.uuid4().hex,
                    severity="error",
                    title="Automated remediation failed",
                    message=f"{incident.title}: {message}",
                    created_at=completed_at,
                    action_label="Open Incident Center",
                    action_payload="generation-incident-center",
                )
            )
        return execution

    def auto_run_for_incident(
        self,
        incident_id: str,
        *,
        trigger: str,
        actor: str | None = "automation",
    ) -> GenerationAutomatedRemediation | None:
        incident = self.repository.get_incident(incident_id)
        if incident is None:
            return None
        policy = self.get_policy(incident.project_id)
        if not policy.enabled:
            return None
        runbooks = self.incident_service.recommend_runbooks(incident_id)
        runbook = next(
            (
                item
                for item in runbooks
                if item.automation_enabled and item.automation_trigger == trigger
            ),
            None,
        )
        if runbook is None:
            return None
        return self.execute(
            incident_id,
            runbook.runbook_id,
            trigger=trigger,
            dry_run=policy.dry_run_default,
            actor=actor,
            confirmed=policy.allow_unattended_mutating,
        )

    def list_executions(
        self,
        incident_id: str,
        *,
        limit: int = 100,
    ) -> list[GenerationAutomatedRemediation]:
        return self.repository.list_automated_remediations(incident_id, limit=limit)

    def mark_rollback(
        self,
        automation_id: str,
        status: str,
        *,
        note: str = "",
        actor: str | None = None,
    ) -> GenerationAutomatedRemediation:
        normalized = status.strip().lower()
        if normalized not in self.VALID_ROLLBACK_STATES:
            raise ValueError(f"Unsupported rollback status: {status}")
        execution = self.repository.get_automated_remediation(automation_id)
        if execution is None:
            raise ValueError("Automated remediation was not found.")
        now = self._now().isoformat()
        updated = replace(
            execution,
            rollback_status=normalized,
            rollback_note=note.strip(),
            actor=self._actor(actor) or execution.actor,
            updated_at=now,
        )
        self.repository.save_automated_remediation(updated)
        incident = self.repository.get_incident(execution.incident_id)
        if incident is not None:
            self._record_event(
                incident,
                updated,
                "Automation rollback updated",
                f"Rollback changed to {normalized.replace('_', ' ')}.",
                kind="automation_rollback",
            )
        return updated

    def _eligibility_reason(
        self,
        incident: GenerationIncident,
        runbook: GenerationIncidentRunbook,
        policy: GenerationAutomationPolicy,
        *,
        trigger: str,
        dry_run: bool,
    ) -> str | None:
        if not policy.enabled:
            return "Remediation automation policy is disabled."
        disallowed = [
            action.action_type
            for action in runbook.automation_actions
            if action.action_type not in policy.allowed_actions
        ]
        if disallowed:
            return f"Policy blocks action(s): {', '.join(sorted(set(disallowed)))}."
        if trigger == "manual" or dry_run:
            return None
        executions = self.repository.list_automated_remediations(
            incident.incident_id,
            runbook_id=runbook.runbook_id,
            trigger=trigger,
            limit=100,
        )
        live_runs = [item for item in executions if not item.dry_run]
        maximum = min(runbook.max_auto_runs, policy.max_auto_runs_per_incident)
        if len(live_runs) >= maximum:
            return f"Maximum automatic run limit reached ({maximum})."
        latest = next((item for item in live_runs if item.completed_at), None)
        cooldown = max(runbook.cooldown_minutes, policy.cooldown_minutes)
        if latest is not None and cooldown > 0:
            completed = self._parse(latest.completed_at)
            if completed is not None and self._now() < completed + timedelta(minutes=cooldown):
                return f"Automation cooldown is active for {cooldown} minute(s)."
        return None

    def _blocked_execution(
        self,
        incident: GenerationIncident,
        runbook: GenerationIncidentRunbook,
        *,
        trigger: str,
        dry_run: bool,
        actor: str | None,
        reason: str,
    ) -> GenerationAutomatedRemediation:
        now = self._now().isoformat()
        execution = GenerationAutomatedRemediation(
            automation_id=uuid.uuid4().hex,
            incident_id=incident.incident_id,
            problem_id=incident.problem_id,
            runbook_id=runbook.runbook_id,
            runbook_name=runbook.name,
            trigger=trigger,
            status="blocked",
            dry_run=dry_run,
            actor=self._actor(actor),
            blocked_reason=reason,
            started_at=now,
            updated_at=now,
            completed_at=now,
        )
        self.repository.save_automated_remediation(execution)
        self._record_event(
            incident,
            execution,
            "Automated remediation blocked",
            reason,
            kind="automation_blocked",
        )
        return execution

    def _run_action(
        self,
        incident: GenerationIncident,
        action: GenerationAutomationAction,
        *,
        position: int,
        dry_run: bool,
        actor: str | None,
    ) -> GenerationAutomationActionResult:
        started_at = self._now().isoformat()
        if dry_run:
            return GenerationAutomationActionResult(
                position=position,
                action_type=action.action_type,
                title=action.title,
                status="planned",
                message=f"Dry Run: {action.action_type} would execute.",
                output={"parameters": action.parameters},
                started_at=started_at,
                completed_at=started_at,
                rollback_instruction=action.rollback_instruction,
            )
        try:
            output = self._dispatch(incident, action, actor=actor)
        except Exception as exc:  # audited and converted into an execution failure
            completed_at = self._now().isoformat()
            return GenerationAutomationActionResult(
                position=position,
                action_type=action.action_type,
                title=action.title,
                status="failed",
                message=str(exc),
                started_at=started_at,
                completed_at=completed_at,
                rollback_instruction=action.rollback_instruction,
            )
        completed_at = self._now().isoformat()
        return GenerationAutomationActionResult(
            position=position,
            action_type=action.action_type,
            title=action.title,
            status="completed",
            message=str(output.pop("message", "Action completed.")),
            output=output,
            started_at=started_at,
            completed_at=completed_at,
            rollback_instruction=action.rollback_instruction,
        )

    def _dispatch(
        self,
        incident: GenerationIncident,
        action: GenerationAutomationAction,
        *,
        actor: str | None,
    ) -> dict[str, object]:
        if action.action_type == "record_workaround":
            return self._record_workaround(incident, actor=actor)
        if action.action_type == "evaluate_sla":
            changed = self.incident_service.evaluate_sla(project_id=incident.project_id)
            return {
                "message": "SLA state evaluated.",
                "changed_incidents": len(changed),
            }
        if action.action_type == "acknowledge_incident":
            count = self.incident_service.acknowledge((incident.incident_id,))
            return {"message": "Incident acknowledged.", "updated_incidents": count}
        if action.action_type == "retry_transient_jobs":
            return self._retry_transient_jobs(incident, action.parameters)
        if action.action_type == "reset_interrupted_jobs":
            return self._reset_interrupted_jobs(incident)
        raise ValueError(f"Action is not implemented: {action.action_type}")

    def _record_workaround(
        self,
        incident: GenerationIncident,
        *,
        actor: str | None,
    ) -> dict[str, object]:
        if self.problem_service is None or not incident.problem_id:
            raise ValueError("Incident is not linked to a known problem with a workaround.")
        problem = self.problem_service.get(incident.problem_id)
        if problem is None or not problem.workaround.strip():
            raise ValueError("Known problem does not contain a documented workaround.")
        update = self.incident_service.add_note(
            incident.incident_id,
            f"Known-problem workaround: {problem.workaround.strip()}",
            actor=actor,
        )
        return {
            "message": "Known-problem workaround added to the incident timeline.",
            "problem_id": problem.problem_id,
            "update_id": update.update_id if update is not None else None,
        }

    def _retry_transient_jobs(
        self,
        incident: GenerationIncident,
        parameters: dict[str, object],
    ) -> dict[str, object]:
        if self.job_repository is None or incident.project_id is None:
            raise ValueError("Job repository or project context is unavailable.")
        jobs = self.job_repository.restore_jobs(incident.project_id)
        failed = [job for job in jobs if job.status == JobStatus.FAILED]
        maximum = int(parameters.get("max_retries", 4))
        maximum = max(0, min(10, maximum))
        result = QueueService(self.job_repository).retry_jobs(
            incident.project_id,
            jobs,
            failed,
            max_retries=maximum,
            transient_only=True,
        )
        return {
            "message": f"Scheduled {result.scheduled} transient failed job(s).",
            "requested": result.requested,
            "scheduled": result.scheduled,
            "blocked": result.blocked,
            "blocked_reasons": result.blocked_reasons,
            "row_numbers": list(result.row_numbers),
        }

    def _reset_interrupted_jobs(
        self,
        incident: GenerationIncident,
    ) -> dict[str, object]:
        if self.job_repository is None or incident.project_id is None:
            raise ValueError("Job repository or project context is unavailable.")
        records = self.job_repository.list_by_project(incident.project_id)
        interrupted = sum(record.status == JobStatus.RUNNING.value for record in records)
        self.job_repository.reset_interrupted(incident.project_id)
        return {
            "message": f"Reset {interrupted} interrupted job(s) to pending.",
            "reset_jobs": interrupted,
        }

    def _record_event(
        self,
        incident: GenerationIncident,
        execution: GenerationAutomatedRemediation,
        title: str,
        message: str,
        *,
        kind: str,
    ) -> None:
        now = self._now().isoformat()
        self.repository.add_activity(
            ActivityEvent(
                event_id=uuid.uuid4().hex,
                project_id=incident.project_id,
                category="generation-automation",
                title=title,
                message=message,
                created_at=now,
                metadata={
                    "automation_id": execution.automation_id,
                    "incident_id": incident.incident_id,
                    "runbook_id": execution.runbook_id,
                    "trigger": execution.trigger,
                    "status": execution.status,
                    "dry_run": execution.dry_run,
                },
            )
        )
        self.repository.add_incident_update(
            GenerationIncidentUpdate(
                update_id=uuid.uuid4().hex,
                incident_id=incident.incident_id,
                kind=kind,
                actor=execution.actor,
                message=message,
                created_at=now,
                metadata={
                    "automation_id": execution.automation_id,
                    "runbook_id": execution.runbook_id or "",
                    "trigger": execution.trigger,
                    "status": execution.status,
                    "dry_run": execution.dry_run,
                },
            )
        )

    @staticmethod
    def _actor(actor: str | None) -> str | None:
        value = (actor or "").strip()
        return value or None

    def _now(self) -> datetime:
        value = self._now_factory()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
