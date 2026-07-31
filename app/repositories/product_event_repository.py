from __future__ import annotations

import json

from app.models.generation_cost_capacity import (
    GenerationCapacityForecast,
    GenerationCostBudgetPolicy,
    GenerationCostCapacitySnapshot,
    GenerationPricingRate,
    GenerationProviderCostEfficiency,
    GenerationSessionCost,
)

from app.models.generation_automation import (
    GenerationAutomatedRemediation,
    GenerationAutomationAction,
    GenerationAutomationActionResult,
    GenerationAutomationPolicy,
)

from app.database.connection import Database
from app.models.generation_incident import (
    GenerationIncident,
    GenerationIncidentActionItem,
    GenerationIncidentRemediation,
    GenerationIncidentRunbook,
    GenerationIncidentReview,
    GenerationIncidentSlaPolicy,
    GenerationIncidentUpdate,
    GenerationRemediationStep,
)
from app.models.generation_problem import GenerationKnownProblem
from app.models.generation_performance import (
    GenerationPerformanceBudget,
    GenerationPerformanceThresholds,
)
from app.models.generation_reliability import (
    GenerationProviderReliability,
    GenerationReliabilitySnapshot,
    GenerationSloPolicy,
)
from app.models.product_events import ActivityEvent, BatchSessionRecord, NotificationRecord


class ProductEventRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_notification(self, record: NotificationRecord) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO notifications(
                    notification_id, severity, title, message, created_at, read,
                    action_label, action_payload
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.notification_id,
                    record.severity,
                    record.title,
                    record.message,
                    record.created_at,
                    int(record.read),
                    record.action_label,
                    record.action_payload,
                ),
            )

    def list_notifications(self, *, unread_only: bool = False, limit: int = 100) -> list[NotificationRecord]:
        where = "WHERE read = 0" if unread_only else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM notifications {where} ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            NotificationRecord(
                notification_id=str(row["notification_id"]),
                severity=str(row["severity"]),
                title=str(row["title"]),
                message=str(row["message"]),
                created_at=str(row["created_at"]),
                read=bool(row["read"]),
                action_label=row["action_label"],
                action_payload=row["action_payload"],
            )
            for row in rows
        ]

    def mark_notification_read(self, notification_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("UPDATE notifications SET read = 1 WHERE notification_id = ?", (notification_id,))

    def delete_notification(self, notification_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM notifications WHERE notification_id = ?", (notification_id,))

    def clear_notifications(self) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM notifications")

    def prune_notifications(self, max_history: int) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                DELETE FROM notifications
                WHERE notification_id NOT IN (
                    SELECT notification_id FROM notifications
                    ORDER BY created_at DESC LIMIT ?
                )
                """,
                (max(1, int(max_history)),),
            )

    def add_activity(self, event: ActivityEvent) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO activity_timeline(
                    event_id, project_id, category, title, message, created_at, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.project_id,
                    event.category,
                    event.title,
                    event.message,
                    event.created_at,
                    json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )

    def list_activity(self, *, project_id: int | None = None, limit: int = 200) -> list[ActivityEvent]:
        where = "WHERE project_id = ?" if project_id is not None else ""
        params: tuple[object, ...] = (project_id, limit) if project_id is not None else (limit,)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM activity_timeline {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            ActivityEvent(
                event_id=str(row["event_id"]),
                project_id=row["project_id"],
                category=str(row["category"]),
                title=str(row["title"]),
                message=str(row["message"]),
                created_at=str(row["created_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in rows
        ]

    def clear_activity(self, *, project_id: int | None = None) -> None:
        with self.database.connect() as connection:
            if project_id is None:
                connection.execute("DELETE FROM activity_timeline")
            else:
                connection.execute("DELETE FROM activity_timeline WHERE project_id = ?", (project_id,))

    def prune_activity(self, max_history: int) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                DELETE FROM activity_timeline
                WHERE event_id NOT IN (
                    SELECT event_id FROM activity_timeline
                    ORDER BY created_at DESC LIMIT ?
                )
                """,
                (max(1, int(max_history)),),
            )

    def add_batch_session(self, record: BatchSessionRecord) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO batch_sessions(
                    session_id, project_id, scope, provider, model, voice,
                    total_jobs, completed_jobs, failed_jobs, skipped_jobs,
                    character_count, report_path, output_path, result, started_at, finished_at,
                    elapsed_seconds, active_seconds, paused_seconds, retry_events,
                    files_per_minute, characters_per_minute, failure_summary_json, monitor_metrics_json,
                    health_score, baseline_session_id, regression_severity, regression_reasons_json,
                    baseline_metrics_json, performance_deltas_json,
                    alert_fingerprint, alert_state, alert_notification_id,
                    alert_created_at, alert_acknowledged_at,
                    incident_id, incident_status
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    record.project_id,
                    record.scope,
                    record.provider,
                    record.model,
                    record.voice,
                    record.total_jobs,
                    record.completed_jobs,
                    record.failed_jobs,
                    record.skipped_jobs,
                    record.character_count,
                    record.report_path,
                    record.output_path,
                    record.result,
                    record.started_at,
                    record.finished_at,
                    max(0.0, record.elapsed_seconds),
                    max(0.0, record.active_seconds),
                    max(0.0, record.paused_seconds),
                    max(0, record.retry_events),
                    max(0.0, record.files_per_minute),
                    max(0.0, record.characters_per_minute),
                    json.dumps(record.failure_summary, ensure_ascii=False, sort_keys=True),
                    json.dumps(record.monitor_metrics, ensure_ascii=False, sort_keys=True),
                    max(0.0, min(100.0, record.health_score)),
                    record.baseline_session_id,
                    record.regression_severity,
                    json.dumps(record.regression_reasons, ensure_ascii=False),
                    json.dumps(record.baseline_metrics, ensure_ascii=False, sort_keys=True),
                    json.dumps(record.performance_deltas, ensure_ascii=False, sort_keys=True),
                    record.alert_fingerprint,
                    record.alert_state,
                    record.alert_notification_id,
                    record.alert_created_at,
                    record.alert_acknowledged_at,
                    record.incident_id,
                    record.incident_status,
                ),
            )

    def update_batch_performance(
        self,
        session_id: str,
        *,
        health_score: float,
        baseline_session_id: str | None,
        regression_severity: str,
        regression_reasons: list[str],
        baseline_metrics: dict[str, object],
        performance_deltas: dict[str, float],
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE batch_sessions
                SET health_score = ?, baseline_session_id = ?, regression_severity = ?,
                    regression_reasons_json = ?, baseline_metrics_json = ?,
                    performance_deltas_json = ?
                WHERE session_id = ?
                """,
                (
                    max(0.0, min(100.0, health_score)),
                    baseline_session_id,
                    regression_severity,
                    json.dumps(regression_reasons, ensure_ascii=False),
                    json.dumps(baseline_metrics, ensure_ascii=False, sort_keys=True),
                    json.dumps(performance_deltas, ensure_ascii=False, sort_keys=True),
                    session_id,
                ),
            )

    def list_batch_sessions(
        self,
        *,
        project_id: int | None = None,
        provider: str | None = None,
        result: str | None = None,
        limit: int = 100,
    ) -> list[BatchSessionRecord]:
        conditions: list[str] = []
        params: list[object] = []
        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)
        if provider:
            conditions.append("provider = ?")
            params.append(provider)
        if result:
            conditions.append("result = ?")
            params.append(result)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM batch_sessions {where} ORDER BY started_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self._batch_session_from_row(row) for row in rows]

    @staticmethod
    def _budget_key(project_id: int | None) -> str:
        return "global" if project_id is None else f"project:{int(project_id)}"

    def get_performance_budget(
        self,
        project_id: int | None,
    ) -> GenerationPerformanceBudget | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_performance_budgets WHERE budget_key = ?",
                (self._budget_key(project_id),),
            ).fetchone()
        if row is None:
            return None
        raw = json.loads(row["thresholds_json"] or "{}")
        allowed = GenerationPerformanceThresholds.__dataclass_fields__
        thresholds = GenerationPerformanceThresholds(
            **{key: value for key, value in raw.items() if key in allowed}
        )
        return GenerationPerformanceBudget(
            project_id=row["project_id"],
            enabled=bool(row["enabled"]),
            thresholds=thresholds,
            alert_cooldown_minutes=int(row["alert_cooldown_minutes"] or 0),
            silence_until=row["silence_until"],
            updated_at=str(row["updated_at"] or ""),
        )

    def save_performance_budget(self, budget: GenerationPerformanceBudget) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_performance_budgets(
                    budget_key, project_id, enabled, thresholds_json,
                    alert_cooldown_minutes, silence_until, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(budget_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    enabled = excluded.enabled,
                    thresholds_json = excluded.thresholds_json,
                    alert_cooldown_minutes = excluded.alert_cooldown_minutes,
                    silence_until = excluded.silence_until,
                    updated_at = excluded.updated_at
                """,
                (
                    self._budget_key(budget.project_id),
                    budget.project_id,
                    int(budget.enabled),
                    json.dumps(budget.thresholds.__dict__, sort_keys=True),
                    max(0, int(budget.alert_cooldown_minutes)),
                    budget.silence_until,
                    budget.updated_at,
                ),
            )

    def delete_performance_budget(self, project_id: int | None) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM generation_performance_budgets WHERE budget_key = ?",
                (self._budget_key(project_id),),
            )

    def update_batch_alert(
        self,
        session_id: str,
        *,
        fingerprint: str | None,
        state: str,
        created_at: str | None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE batch_sessions
                SET alert_fingerprint = ?, alert_state = ?, alert_created_at = ?,
                    alert_notification_id = NULL, alert_acknowledged_at = NULL
                WHERE session_id = ?
                """,
                (fingerprint, state, created_at, session_id),
            )

    def attach_batch_alert_notification(self, session_id: str, notification_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE batch_sessions SET alert_notification_id = ? WHERE session_id = ?",
                (notification_id, session_id),
            )

    def has_recent_emitted_alert(self, fingerprint: str, since: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM batch_sessions
                WHERE alert_fingerprint = ?
                  AND alert_notification_id IS NOT NULL
                  AND alert_created_at >= ?
                LIMIT 1
                """,
                (fingerprint, since),
            ).fetchone()
        return row is not None

    def acknowledge_batch_alerts(self, session_ids: tuple[str, ...], acknowledged_at: str) -> int:
        placeholders = ",".join("?" for _ in session_ids)
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE batch_sessions
                SET alert_state = 'acknowledged', alert_acknowledged_at = ?
                WHERE session_id IN ({placeholders})
                  AND alert_state = 'open'
                """,
                (acknowledged_at, *session_ids),
            )
            return int(cursor.rowcount)



    def add_incident(self, incident: GenerationIncident) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_incidents(
                    incident_id, project_id, alert_fingerprint, severity, status,
                    title, summary, first_session_id, latest_session_id,
                    occurrence_count, session_ids_json, created_at, updated_at,
                    acknowledged_at, resolved_at, resolution_note, assigned_to,
                    priority, response_due_at, resolution_due_at, sla_state,
                    escalation_level, escalated_at, last_sla_notification_level
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    alert_fingerprint = excluded.alert_fingerprint,
                    severity = excluded.severity,
                    status = excluded.status,
                    title = excluded.title,
                    summary = excluded.summary,
                    latest_session_id = excluded.latest_session_id,
                    occurrence_count = excluded.occurrence_count,
                    session_ids_json = excluded.session_ids_json,
                    updated_at = excluded.updated_at,
                    acknowledged_at = excluded.acknowledged_at,
                    resolved_at = excluded.resolved_at,
                    resolution_note = excluded.resolution_note,
                    assigned_to = excluded.assigned_to,
                    priority = excluded.priority,
                    response_due_at = excluded.response_due_at,
                    resolution_due_at = excluded.resolution_due_at,
                    sla_state = excluded.sla_state,
                    escalation_level = excluded.escalation_level,
                    escalated_at = excluded.escalated_at,
                    last_sla_notification_level = excluded.last_sla_notification_level
                """,
                (
                    incident.incident_id,
                    incident.project_id,
                    incident.alert_fingerprint,
                    incident.severity,
                    incident.status,
                    incident.title,
                    incident.summary,
                    incident.first_session_id,
                    incident.latest_session_id,
                    max(1, int(incident.occurrence_count)),
                    json.dumps(list(incident.session_ids), ensure_ascii=False),
                    incident.created_at,
                    incident.updated_at,
                    incident.acknowledged_at,
                    incident.resolved_at,
                    incident.resolution_note,
                    incident.assigned_to,
                    incident.priority,
                    incident.response_due_at,
                    incident.resolution_due_at,
                    incident.sla_state,
                    max(0, int(incident.escalation_level)),
                    incident.escalated_at,
                    max(0, int(incident.last_sla_notification_level)),
                ),
            )

    def get_incident(self, incident_id: str) -> GenerationIncident | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_incidents WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
        return self._incident_from_row(row) if row is not None else None

    def find_active_incident(
        self,
        *,
        project_id: int | None,
        alert_fingerprint: str,
    ) -> GenerationIncident | None:
        if project_id is None:
            project_clause = "project_id IS NULL"
            params: tuple[object, ...] = (alert_fingerprint,)
        else:
            project_clause = "project_id = ?"
            params = (alert_fingerprint, project_id)
        with self.database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM generation_incidents
                WHERE alert_fingerprint = ?
                  AND {project_clause}
                  AND status IN ('open', 'acknowledged')
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._incident_from_row(row) if row is not None else None

    def list_incidents(
        self,
        *,
        project_id: int | None = None,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 500,
    ) -> list[GenerationIncident]:
        conditions: list[str] = []
        params: list[object] = []
        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_incidents {where} "
                "ORDER BY updated_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self._incident_from_row(row) for row in rows]

    def link_batch_incident(self, session_id: str, incident_id: str, status: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE batch_sessions
                SET incident_id = ?, incident_status = ?
                WHERE session_id = ?
                """,
                (incident_id, status, session_id),
            )

    def update_incident_status(
        self,
        incident_ids: tuple[str, ...],
        *,
        status: str,
        updated_at: str,
        acknowledged_at: str | None = None,
        resolved_at: str | None = None,
        resolution_note: str | None = None,
    ) -> int:
        if not incident_ids:
            return 0
        placeholders = ",".join("?" for _ in incident_ids)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"""
                UPDATE generation_incidents
                SET status = ?, updated_at = ?,
                    acknowledged_at = ?, resolved_at = ?, resolution_note = ?
                WHERE incident_id IN ({placeholders})
                """,
                (
                    status,
                    updated_at,
                    acknowledged_at,
                    resolved_at,
                    resolution_note,
                    *incident_ids,
                ),
            )
            connection.execute(
                f"""
                UPDATE batch_sessions
                SET incident_status = ?
                WHERE incident_id IN ({placeholders})
                """,
                (status, *incident_ids),
            )
            return int(cursor.rowcount)

    def update_incident_assignment(
        self,
        incident_ids: tuple[str, ...],
        *,
        assigned_to: str | None,
        updated_at: str,
    ) -> int:
        if not incident_ids:
            return 0
        placeholders = ",".join("?" for _ in incident_ids)
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE generation_incidents
                SET assigned_to = ?, updated_at = ?
                WHERE incident_id IN ({placeholders})
                """,
                (assigned_to, updated_at, *incident_ids),
            )
        return int(cursor.rowcount)

    def update_incident_sla(
        self,
        incident_id: str,
        *,
        response_due_at: str | None,
        resolution_due_at: str | None,
        sla_state: str,
        escalation_level: int,
        escalated_at: str | None,
        last_sla_notification_level: int,
        updated_at: str,
    ) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE generation_incidents
                SET response_due_at = ?, resolution_due_at = ?, sla_state = ?,
                    escalation_level = ?, escalated_at = ?,
                    last_sla_notification_level = ?, updated_at = ?
                WHERE incident_id = ?
                """,
                (
                    response_due_at,
                    resolution_due_at,
                    sla_state,
                    max(0, int(escalation_level)),
                    escalated_at,
                    max(0, int(last_sla_notification_level)),
                    updated_at,
                    incident_id,
                ),
            )
        return int(cursor.rowcount)

    def save_incident_sla_policy(self, policy: GenerationIncidentSlaPolicy) -> None:
        with self.database.transaction() as connection:
            if policy.project_id is None:
                row = connection.execute(
                    "SELECT policy_id FROM generation_incident_sla_policies "
                    "WHERE project_id IS NULL ORDER BY policy_id LIMIT 1"
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT policy_id FROM generation_incident_sla_policies "
                    "WHERE project_id = ? LIMIT 1",
                    (policy.project_id,),
                ).fetchone()
            values = (
                policy.project_id,
                int(policy.enabled),
                max(1, int(policy.critical_response_minutes)),
                max(1, int(policy.critical_resolution_minutes)),
                max(1, int(policy.warning_response_minutes)),
                max(1, int(policy.warning_resolution_minutes)),
                policy.updated_at,
            )
            if row is None:
                connection.execute(
                    """
                    INSERT INTO generation_incident_sla_policies(
                        project_id, enabled, critical_response_minutes,
                        critical_resolution_minutes, warning_response_minutes,
                        warning_resolution_minutes, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            else:
                connection.execute(
                    """
                    UPDATE generation_incident_sla_policies
                    SET project_id = ?, enabled = ?, critical_response_minutes = ?,
                        critical_resolution_minutes = ?, warning_response_minutes = ?,
                        warning_resolution_minutes = ?, updated_at = ?
                    WHERE policy_id = ?
                    """,
                    (*values, int(row["policy_id"])),
                )

    def get_incident_sla_policy(
        self,
        project_id: int | None,
    ) -> GenerationIncidentSlaPolicy | None:
        with self.database.connect() as connection:
            if project_id is None:
                row = connection.execute(
                    "SELECT * FROM generation_incident_sla_policies "
                    "WHERE project_id IS NULL ORDER BY policy_id LIMIT 1"
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM generation_incident_sla_policies "
                    "WHERE project_id = ? LIMIT 1",
                    (project_id,),
                ).fetchone()
        return self._incident_sla_policy_from_row(row) if row is not None else None

    def add_incident_update(self, update: GenerationIncidentUpdate) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO generation_incident_updates(
                    update_id, incident_id, kind, actor, message,
                    metadata_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update.update_id,
                    update.incident_id,
                    update.kind,
                    update.actor,
                    update.message,
                    json.dumps(update.metadata, ensure_ascii=False),
                    update.created_at,
                ),
            )

    def list_incident_updates(
        self,
        incident_id: str,
        *,
        limit: int = 200,
    ) -> list[GenerationIncidentUpdate]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM generation_incident_updates
                WHERE incident_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (incident_id, max(1, int(limit))),
            ).fetchall()
        return [self._incident_update_from_row(row) for row in rows]

    def save_incident_runbook(self, runbook: GenerationIncidentRunbook) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_incident_runbooks(
                    runbook_id, project_id, name, description, severity_filter,
                    fingerprint_pattern, steps_json, enabled, automation_enabled,
                    automation_trigger, automation_actions_json, dry_run_only,
                    max_auto_runs, cooldown_minutes, rollback_instructions,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(runbook_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    name = excluded.name,
                    description = excluded.description,
                    severity_filter = excluded.severity_filter,
                    fingerprint_pattern = excluded.fingerprint_pattern,
                    steps_json = excluded.steps_json,
                    enabled = excluded.enabled,
                    automation_enabled = excluded.automation_enabled,
                    automation_trigger = excluded.automation_trigger,
                    automation_actions_json = excluded.automation_actions_json,
                    dry_run_only = excluded.dry_run_only,
                    max_auto_runs = excluded.max_auto_runs,
                    cooldown_minutes = excluded.cooldown_minutes,
                    rollback_instructions = excluded.rollback_instructions,
                    updated_at = excluded.updated_at
                """,
                (
                    runbook.runbook_id,
                    runbook.project_id,
                    runbook.name,
                    runbook.description,
                    runbook.severity_filter,
                    runbook.fingerprint_pattern,
                    json.dumps(list(runbook.steps), ensure_ascii=False),
                    int(runbook.enabled),
                    int(runbook.automation_enabled),
                    runbook.automation_trigger,
                    json.dumps(
                        [self._automation_action_payload(action) for action in runbook.automation_actions],
                        ensure_ascii=False,
                    ),
                    int(runbook.dry_run_only),
                    int(runbook.max_auto_runs),
                    int(runbook.cooldown_minutes),
                    runbook.rollback_instructions,
                    runbook.created_at,
                    runbook.updated_at,
                ),
            )

    def get_incident_runbook(
        self,
        runbook_id: str,
    ) -> GenerationIncidentRunbook | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_incident_runbooks WHERE runbook_id = ?",
                (runbook_id,),
            ).fetchone()
        return self._incident_runbook_from_row(row) if row is not None else None

    def list_incident_runbooks(
        self,
        *,
        project_id: int | None = None,
        include_global: bool = True,
        enabled_only: bool = False,
    ) -> list[GenerationIncidentRunbook]:
        conditions: list[str] = []
        params: list[object] = []
        if project_id is not None:
            if include_global:
                conditions.append("(project_id IS NULL OR project_id = ?)")
            else:
                conditions.append("project_id = ?")
            params.append(project_id)
        elif not include_global:
            conditions.append("project_id IS NULL")
        if enabled_only:
            conditions.append("enabled = 1")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_incident_runbooks {where} "
                "ORDER BY project_id IS NULL, name COLLATE NOCASE, updated_at DESC",
                tuple(params),
            ).fetchall()
        return [self._incident_runbook_from_row(row) for row in rows]

    def delete_incident_runbook(self, runbook_id: str) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM generation_incident_runbooks WHERE runbook_id = ?",
                (runbook_id,),
            )
        return int(cursor.rowcount)

    def save_incident_remediation(
        self,
        remediation: GenerationIncidentRemediation,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_incident_remediations(
                    remediation_id, incident_id, runbook_id, runbook_name, status,
                    steps_json, actor, started_at, updated_at, completed_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(remediation_id) DO UPDATE SET
                    runbook_id = excluded.runbook_id,
                    runbook_name = excluded.runbook_name,
                    status = excluded.status,
                    steps_json = excluded.steps_json,
                    actor = excluded.actor,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                (
                    remediation.remediation_id,
                    remediation.incident_id,
                    remediation.runbook_id,
                    remediation.runbook_name,
                    remediation.status,
                    json.dumps(
                        [self._remediation_step_payload(step) for step in remediation.steps],
                        ensure_ascii=False,
                    ),
                    remediation.actor,
                    remediation.started_at,
                    remediation.updated_at,
                    remediation.completed_at,
                ),
            )

    def get_incident_remediation(
        self,
        remediation_id: str,
    ) -> GenerationIncidentRemediation | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_incident_remediations "
                "WHERE remediation_id = ?",
                (remediation_id,),
            ).fetchone()
        return self._incident_remediation_from_row(row) if row is not None else None

    def find_active_incident_remediation(
        self,
        incident_id: str,
    ) -> GenerationIncidentRemediation | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM generation_incident_remediations
                WHERE incident_id = ? AND status = 'active'
                ORDER BY updated_at DESC LIMIT 1
                """,
                (incident_id,),
            ).fetchone()
        return self._incident_remediation_from_row(row) if row is not None else None

    def list_incident_remediations(
        self,
        incident_id: str,
        *,
        limit: int = 100,
    ) -> list[GenerationIncidentRemediation]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM generation_incident_remediations
                WHERE incident_id = ?
                ORDER BY started_at DESC LIMIT ?
                """,
                (incident_id, max(1, int(limit))),
            ).fetchall()
        return [self._incident_remediation_from_row(row) for row in rows]

    def save_remediation_automation_policy(
        self,
        policy: GenerationAutomationPolicy,
    ) -> None:
        key = "global" if policy.project_id is None else f"project:{policy.project_id}"
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_remediation_automation_policies(
                    policy_key, project_id, enabled, dry_run_default,
                    allowed_actions_json, require_confirmation_for_mutating,
                    allow_unattended_mutating, max_auto_runs_per_incident,
                    cooldown_minutes, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    enabled = excluded.enabled,
                    dry_run_default = excluded.dry_run_default,
                    allowed_actions_json = excluded.allowed_actions_json,
                    require_confirmation_for_mutating =
                        excluded.require_confirmation_for_mutating,
                    allow_unattended_mutating = excluded.allow_unattended_mutating,
                    max_auto_runs_per_incident = excluded.max_auto_runs_per_incident,
                    cooldown_minutes = excluded.cooldown_minutes,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    policy.project_id,
                    int(policy.enabled),
                    int(policy.dry_run_default),
                    json.dumps(list(policy.allowed_actions), ensure_ascii=False),
                    int(policy.require_confirmation_for_mutating),
                    int(policy.allow_unattended_mutating),
                    int(policy.max_auto_runs_per_incident),
                    int(policy.cooldown_minutes),
                    policy.updated_at,
                ),
            )

    def get_remediation_automation_policy(
        self,
        project_id: int | None,
    ) -> GenerationAutomationPolicy | None:
        key = "global" if project_id is None else f"project:{project_id}"
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_remediation_automation_policies "
                "WHERE policy_key = ?",
                (key,),
            ).fetchone()
        return self._automation_policy_from_row(row) if row is not None else None

    def save_automated_remediation(
        self,
        execution: GenerationAutomatedRemediation,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_automated_remediations(
                    automation_id, incident_id, problem_id, runbook_id,
                    runbook_name, trigger, status, dry_run, action_results_json,
                    actor, blocked_reason, rollback_status, rollback_note,
                    started_at, updated_at, completed_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(automation_id) DO UPDATE SET
                    problem_id = excluded.problem_id,
                    runbook_name = excluded.runbook_name,
                    trigger = excluded.trigger,
                    status = excluded.status,
                    dry_run = excluded.dry_run,
                    action_results_json = excluded.action_results_json,
                    actor = excluded.actor,
                    blocked_reason = excluded.blocked_reason,
                    rollback_status = excluded.rollback_status,
                    rollback_note = excluded.rollback_note,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                (
                    execution.automation_id,
                    execution.incident_id,
                    execution.problem_id,
                    execution.runbook_id,
                    execution.runbook_name,
                    execution.trigger,
                    execution.status,
                    int(execution.dry_run),
                    json.dumps(
                        [
                            self._automation_action_result_payload(result)
                            for result in execution.action_results
                        ],
                        ensure_ascii=False,
                    ),
                    execution.actor,
                    execution.blocked_reason,
                    execution.rollback_status,
                    execution.rollback_note,
                    execution.started_at,
                    execution.updated_at,
                    execution.completed_at,
                ),
            )

    def get_automated_remediation(
        self,
        automation_id: str,
    ) -> GenerationAutomatedRemediation | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_automated_remediations "
                "WHERE automation_id = ?",
                (automation_id,),
            ).fetchone()
        return self._automated_remediation_from_row(row) if row is not None else None

    def find_running_automated_remediation(
        self,
        incident_id: str,
    ) -> GenerationAutomatedRemediation | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM generation_automated_remediations
                WHERE incident_id = ? AND status = 'running'
                ORDER BY started_at DESC LIMIT 1
                """,
                (incident_id,),
            ).fetchone()
        return self._automated_remediation_from_row(row) if row is not None else None

    def list_automated_remediations(
        self,
        incident_id: str,
        *,
        runbook_id: str | None = None,
        trigger: str | None = None,
        limit: int = 100,
    ) -> list[GenerationAutomatedRemediation]:
        conditions = ["incident_id = ?"]
        params: list[object] = [incident_id]
        if runbook_id is not None:
            conditions.append("runbook_id = ?")
            params.append(runbook_id)
        if trigger is not None:
            conditions.append("trigger = ?")
            params.append(trigger)
        params.append(max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_automated_remediations "
                f"WHERE {' AND '.join(conditions)} "
                "ORDER BY started_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self._automated_remediation_from_row(row) for row in rows]

    def save_incident_review(self, review: GenerationIncidentReview) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_incident_reviews(
                    review_id, incident_id, status, impact_summary,
                    root_cause_category, root_cause, contributing_factors_json,
                    detection_gap, resolution_summary, lessons_learned, reviewer,
                    created_at, updated_at, completed_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    status = excluded.status,
                    impact_summary = excluded.impact_summary,
                    root_cause_category = excluded.root_cause_category,
                    root_cause = excluded.root_cause,
                    contributing_factors_json = excluded.contributing_factors_json,
                    detection_gap = excluded.detection_gap,
                    resolution_summary = excluded.resolution_summary,
                    lessons_learned = excluded.lessons_learned,
                    reviewer = excluded.reviewer,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                (
                    review.review_id,
                    review.incident_id,
                    review.status,
                    review.impact_summary,
                    review.root_cause_category,
                    review.root_cause,
                    json.dumps(list(review.contributing_factors), ensure_ascii=False),
                    review.detection_gap,
                    review.resolution_summary,
                    review.lessons_learned,
                    review.reviewer,
                    review.created_at,
                    review.updated_at,
                    review.completed_at,
                ),
            )

    def get_incident_review(
        self,
        incident_id: str,
    ) -> GenerationIncidentReview | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_incident_reviews WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
        return self._incident_review_from_row(row) if row is not None else None

    def list_incident_reviews(
        self,
        *,
        project_id: int | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[GenerationIncidentReview]:
        conditions: list[str] = []
        params: list[object] = []
        if project_id is not None:
            conditions.append("i.project_id = ?")
            params.append(project_id)
        if status:
            conditions.append("r.status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT r.* FROM generation_incident_reviews r
                JOIN generation_incidents i ON i.incident_id = r.incident_id
                {where}
                ORDER BY r.updated_at DESC LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._incident_review_from_row(row) for row in rows]

    def save_incident_action_item(
        self,
        action: GenerationIncidentActionItem,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_incident_action_items(
                    action_id, review_id, incident_id, title, status, priority,
                    owner, due_at, note, created_at, updated_at, completed_at,
                    overdue_notified_at, problem_id
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    priority = excluded.priority,
                    owner = excluded.owner,
                    due_at = excluded.due_at,
                    note = excluded.note,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at,
                    overdue_notified_at = excluded.overdue_notified_at,
                    problem_id = excluded.problem_id
                """,
                (
                    action.action_id,
                    action.review_id,
                    action.incident_id,
                    action.title,
                    action.status,
                    action.priority,
                    action.owner,
                    action.due_at,
                    action.note,
                    action.created_at,
                    action.updated_at,
                    action.completed_at,
                    action.overdue_notified_at,
                    action.problem_id,
                ),
            )

    def get_incident_action_item(
        self,
        action_id: str,
    ) -> GenerationIncidentActionItem | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_incident_action_items WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        return self._incident_action_from_row(row) if row is not None else None

    def list_incident_action_items(
        self,
        *,
        incident_id: str | None = None,
        review_id: str | None = None,
        project_id: int | None = None,
        problem_id: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[GenerationIncidentActionItem]:
        conditions: list[str] = []
        params: list[object] = []
        if incident_id is not None:
            conditions.append("a.incident_id = ?")
            params.append(incident_id)
        if review_id is not None:
            conditions.append("a.review_id = ?")
            params.append(review_id)
        if project_id is not None:
            conditions.append("i.project_id = ?")
            params.append(project_id)
        if problem_id is not None:
            conditions.append("a.problem_id = ?")
            params.append(problem_id)
        if status:
            conditions.append("a.status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT a.* FROM generation_incident_action_items a
                JOIN generation_incidents i ON i.incident_id = a.incident_id
                {where}
                ORDER BY
                    CASE a.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,
                    CASE WHEN a.due_at IS NULL THEN 1 ELSE 0 END,
                    a.due_at, a.created_at
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._incident_action_from_row(row) for row in rows]

    def delete_incident_action_item(self, action_id: str) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM generation_incident_action_items WHERE action_id = ?",
                (action_id,),
            )
        return int(cursor.rowcount)

    def save_known_problem(self, problem: GenerationKnownProblem) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_known_problems(
                    problem_id, project_id, problem_key, title, description, status,
                    severity, root_cause_category, workaround, permanent_fix, owner,
                    fingerprints_json, incident_ids_json, occurrence_count,
                    first_seen_at, last_seen_at, monitoring_until, created_at,
                    updated_at, closed_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(problem_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    problem_key = excluded.problem_key,
                    title = excluded.title,
                    description = excluded.description,
                    status = excluded.status,
                    severity = excluded.severity,
                    root_cause_category = excluded.root_cause_category,
                    workaround = excluded.workaround,
                    permanent_fix = excluded.permanent_fix,
                    owner = excluded.owner,
                    fingerprints_json = excluded.fingerprints_json,
                    incident_ids_json = excluded.incident_ids_json,
                    occurrence_count = excluded.occurrence_count,
                    first_seen_at = excluded.first_seen_at,
                    last_seen_at = excluded.last_seen_at,
                    monitoring_until = excluded.monitoring_until,
                    updated_at = excluded.updated_at,
                    closed_at = excluded.closed_at
                """,
                (
                    problem.problem_id,
                    problem.project_id,
                    problem.problem_key,
                    problem.title,
                    problem.description,
                    problem.status,
                    problem.severity,
                    problem.root_cause_category,
                    problem.workaround,
                    problem.permanent_fix,
                    problem.owner,
                    json.dumps(list(problem.fingerprints), ensure_ascii=False),
                    json.dumps(list(problem.incident_ids), ensure_ascii=False),
                    max(0, int(problem.occurrence_count)),
                    problem.first_seen_at,
                    problem.last_seen_at,
                    problem.monitoring_until,
                    problem.created_at,
                    problem.updated_at,
                    problem.closed_at,
                ),
            )

    def get_known_problem(self, problem_id: str) -> GenerationKnownProblem | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_known_problems WHERE problem_id = ?",
                (problem_id,),
            ).fetchone()
        return self._known_problem_from_row(row) if row is not None else None

    def find_known_problem_by_key(
        self,
        *,
        project_id: int | None,
        problem_key: str,
        active_only: bool = True,
    ) -> GenerationKnownProblem | None:
        conditions = ["problem_key = ?"]
        params: list[object] = [problem_key]
        if project_id is None:
            conditions.append("project_id IS NULL")
        else:
            conditions.append("project_id = ?")
            params.append(project_id)
        if active_only:
            conditions.append("status != 'closed'")
        with self.database.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM generation_known_problems WHERE {' AND '.join(conditions)} "
                "ORDER BY updated_at DESC LIMIT 1",
                tuple(params),
            ).fetchone()
        return self._known_problem_from_row(row) if row is not None else None

    def list_known_problems(
        self,
        *,
        project_id: int | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[GenerationKnownProblem]:
        conditions: list[str] = []
        params: list[object] = []
        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_known_problems {where} "
                "ORDER BY CASE status "
                "WHEN 'investigating' THEN 0 WHEN 'known_error' THEN 1 "
                "WHEN 'fix_planned' THEN 2 WHEN 'monitoring' THEN 3 ELSE 4 END, "
                "last_seen_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self._known_problem_from_row(row) for row in rows]

    def link_problem_incident(
        self,
        problem_id: str,
        incident_id: str,
        *,
        problem_status: str,
        match_reason: str,
        linked_at: str,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_problem_incidents(
                    problem_id, incident_id, match_reason, linked_at
                ) VALUES(?, ?, ?, ?)
                ON CONFLICT(problem_id, incident_id) DO UPDATE SET
                    match_reason = excluded.match_reason, linked_at = excluded.linked_at
                """,
                (problem_id, incident_id, match_reason, linked_at),
            )
            connection.execute(
                """
                UPDATE generation_incidents
                SET problem_id = ?, problem_status = ?
                WHERE incident_id = ?
                """,
                (problem_id, problem_status, incident_id),
            )

    def update_problem_status_links(self, problem_id: str, status: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE generation_incidents SET problem_status = ? WHERE problem_id = ?",
                (status, problem_id),
            )

    def list_problem_incident_ids(self, problem_id: str) -> tuple[str, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT incident_id FROM generation_problem_incidents
                WHERE problem_id = ? ORDER BY linked_at, incident_id
                """,
                (problem_id,),
            ).fetchall()
        return tuple(str(row["incident_id"]) for row in rows)

    def link_action_to_problem(self, action_id: str, problem_id: str | None) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE generation_incident_action_items SET problem_id = ? WHERE action_id = ?",
                (problem_id, action_id),
            )
        return int(cursor.rowcount)

    @staticmethod
    def _known_problem_from_row(row) -> GenerationKnownProblem:
        return GenerationKnownProblem(
            problem_id=str(row["problem_id"]),
            project_id=row["project_id"],
            problem_key=str(row["problem_key"]),
            title=str(row["title"]),
            description=str(row["description"] or ""),
            status=str(row["status"] or "investigating"),
            severity=str(row["severity"] or "critical"),
            root_cause_category=str(row["root_cause_category"] or "unknown"),
            workaround=str(row["workaround"] or ""),
            permanent_fix=str(row["permanent_fix"] or ""),
            owner=row["owner"],
            fingerprints=tuple(
                str(value) for value in json.loads(row["fingerprints_json"] or "[]")
            ),
            incident_ids=tuple(
                str(value) for value in json.loads(row["incident_ids_json"] or "[]")
            ),
            occurrence_count=int(row["occurrence_count"] or 0),
            first_seen_at=str(row["first_seen_at"]),
            last_seen_at=str(row["last_seen_at"]),
            monitoring_until=row["monitoring_until"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            closed_at=row["closed_at"],
        )

    @staticmethod
    def _incident_review_from_row(row) -> GenerationIncidentReview:
        return GenerationIncidentReview(
            review_id=str(row["review_id"]),
            incident_id=str(row["incident_id"]),
            status=str(row["status"] or "draft"),
            impact_summary=str(row["impact_summary"] or ""),
            root_cause_category=str(row["root_cause_category"] or "unknown"),
            root_cause=str(row["root_cause"] or ""),
            contributing_factors=tuple(
                str(value)
                for value in json.loads(row["contributing_factors_json"] or "[]")
            ),
            detection_gap=str(row["detection_gap"] or ""),
            resolution_summary=str(row["resolution_summary"] or ""),
            lessons_learned=str(row["lessons_learned"] or ""),
            reviewer=row["reviewer"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _incident_action_from_row(row) -> GenerationIncidentActionItem:
        return GenerationIncidentActionItem(
            action_id=str(row["action_id"]),
            review_id=str(row["review_id"]),
            incident_id=str(row["incident_id"]),
            title=str(row["title"]),
            status=str(row["status"] or "open"),
            priority=str(row["priority"] or "p2"),
            owner=row["owner"],
            due_at=row["due_at"],
            note=str(row["note"] or ""),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=row["completed_at"],
            overdue_notified_at=row["overdue_notified_at"],
            problem_id=row["problem_id"] if "problem_id" in set(row.keys()) else None,
        )

    @staticmethod
    def _incident_from_row(row) -> GenerationIncident:
        session_ids = tuple(str(value) for value in json.loads(row["session_ids_json"] or "[]"))
        keys = set(row.keys())
        return GenerationIncident(
            incident_id=str(row["incident_id"]),
            project_id=row["project_id"],
            alert_fingerprint=str(row["alert_fingerprint"]),
            severity=str(row["severity"]),
            status=str(row["status"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            first_session_id=str(row["first_session_id"]),
            latest_session_id=str(row["latest_session_id"]),
            occurrence_count=int(row["occurrence_count"] or 1),
            session_ids=session_ids,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            acknowledged_at=row["acknowledged_at"],
            resolved_at=row["resolved_at"],
            resolution_note=row["resolution_note"],
            assigned_to=row["assigned_to"] if "assigned_to" in keys else None,
            priority=str(row["priority"] or "p1") if "priority" in keys else "p1",
            response_due_at=row["response_due_at"] if "response_due_at" in keys else None,
            resolution_due_at=(
                row["resolution_due_at"] if "resolution_due_at" in keys else None
            ),
            sla_state=(
                str(row["sla_state"] or "not_configured")
                if "sla_state" in keys
                else "not_configured"
            ),
            escalation_level=(
                int(row["escalation_level"] or 0) if "escalation_level" in keys else 0
            ),
            escalated_at=row["escalated_at"] if "escalated_at" in keys else None,
            last_sla_notification_level=(
                int(row["last_sla_notification_level"] or 0)
                if "last_sla_notification_level" in keys
                else 0
            ),
            problem_id=row["problem_id"] if "problem_id" in keys else None,
            problem_status=(
                str(row["problem_status"] or "none")
                if "problem_status" in keys
                else "none"
            ),
        )

    @classmethod
    def _incident_runbook_from_row(cls, row) -> GenerationIncidentRunbook:
        keys = set(row.keys())
        raw_actions = (
            json.loads(row["automation_actions_json"] or "[]")
            if "automation_actions_json" in keys
            else []
        )
        return GenerationIncidentRunbook(
            runbook_id=str(row["runbook_id"]),
            project_id=row["project_id"],
            name=str(row["name"]),
            description=str(row["description"] or ""),
            severity_filter=str(row["severity_filter"] or "any"),
            fingerprint_pattern=str(row["fingerprint_pattern"] or ""),
            steps=tuple(str(value) for value in json.loads(row["steps_json"] or "[]")),
            enabled=bool(row["enabled"]),
            automation_enabled=(
                bool(row["automation_enabled"]) if "automation_enabled" in keys else False
            ),
            automation_trigger=(
                str(row["automation_trigger"] or "manual")
                if "automation_trigger" in keys
                else "manual"
            ),
            automation_actions=tuple(
                cls._automation_action_from_payload(item) for item in raw_actions
            ),
            dry_run_only=(
                bool(row["dry_run_only"]) if "dry_run_only" in keys else True
            ),
            max_auto_runs=(
                int(row["max_auto_runs"] or 1) if "max_auto_runs" in keys else 1
            ),
            cooldown_minutes=(
                int(row["cooldown_minutes"])
                if "cooldown_minutes" in keys and row["cooldown_minutes"] is not None
                else 60
            ),
            rollback_instructions=(
                str(row["rollback_instructions"] or "")
                if "rollback_instructions" in keys
                else ""
            ),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _automation_action_payload(
        action: GenerationAutomationAction,
    ) -> dict[str, object]:
        return {
            "action_type": action.action_type,
            "title": action.title,
            "parameters": action.parameters,
            "rollback_instruction": action.rollback_instruction,
        }

    @staticmethod
    def _automation_action_from_payload(
        payload: dict[str, object],
    ) -> GenerationAutomationAction:
        raw_parameters = payload.get("parameters", {})
        parameters = raw_parameters if isinstance(raw_parameters, dict) else {}
        return GenerationAutomationAction(
            action_type=str(payload.get("action_type", "")),
            title=str(payload.get("title", "")),
            parameters={str(key): value for key, value in parameters.items()},
            rollback_instruction=str(payload.get("rollback_instruction", "")),
        )

    @staticmethod
    def _automation_action_result_payload(
        result: GenerationAutomationActionResult,
    ) -> dict[str, object]:
        return {
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

    @staticmethod
    def _automation_policy_from_row(row) -> GenerationAutomationPolicy:
        return GenerationAutomationPolicy(
            project_id=row["project_id"],
            enabled=bool(row["enabled"]),
            dry_run_default=bool(row["dry_run_default"]),
            allowed_actions=tuple(
                str(value) for value in json.loads(row["allowed_actions_json"] or "[]")
            ),
            require_confirmation_for_mutating=bool(
                row["require_confirmation_for_mutating"]
            ),
            allow_unattended_mutating=bool(row["allow_unattended_mutating"]),
            max_auto_runs_per_incident=int(
                row["max_auto_runs_per_incident"] or 2
            ),
            cooldown_minutes=(
                int(row["cooldown_minutes"])
                if row["cooldown_minutes"] is not None
                else 60
            ),
            updated_at=str(row["updated_at"]),
        )

    @classmethod
    def _automated_remediation_from_row(cls, row) -> GenerationAutomatedRemediation:
        raw_results = json.loads(row["action_results_json"] or "[]")
        results = tuple(
            GenerationAutomationActionResult(
                position=int(item.get("position", index)),
                action_type=str(item.get("action_type", "")),
                title=str(item.get("title", "")),
                status=str(item.get("status", "pending")),
                message=str(item.get("message", "")),
                output=(
                    {str(key): value for key, value in item.get("output", {}).items()}
                    if isinstance(item.get("output", {}), dict)
                    else {}
                ),
                started_at=str(item.get("started_at", "")),
                completed_at=item.get("completed_at"),
                rollback_instruction=str(item.get("rollback_instruction", "")),
            )
            for index, item in enumerate(raw_results)
        )
        return GenerationAutomatedRemediation(
            automation_id=str(row["automation_id"]),
            incident_id=str(row["incident_id"]),
            problem_id=row["problem_id"],
            runbook_id=(str(row["runbook_id"]) if row["runbook_id"] is not None else None),
            runbook_name=str(row["runbook_name"]),
            trigger=str(row["trigger"] or "manual"),
            status=str(row["status"] or "running"),
            dry_run=bool(row["dry_run"]),
            action_results=results,
            actor=row["actor"],
            blocked_reason=row["blocked_reason"],
            rollback_status=str(row["rollback_status"] or "not_requested"),
            rollback_note=str(row["rollback_note"] or ""),
            started_at=str(row["started_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _remediation_step_payload(step: GenerationRemediationStep) -> dict[str, object]:
        return {
            "position": int(step.position),
            "title": step.title,
            "status": step.status,
            "note": step.note,
            "actor": step.actor,
            "completed_at": step.completed_at,
        }

    @classmethod
    def _incident_remediation_from_row(cls, row) -> GenerationIncidentRemediation:
        raw_steps = json.loads(row["steps_json"] or "[]")
        steps = tuple(
            GenerationRemediationStep(
                position=int(item.get("position", index)),
                title=str(item.get("title", "")),
                status=str(item.get("status", "pending")),
                note=str(item.get("note", "")),
                actor=item.get("actor"),
                completed_at=item.get("completed_at"),
            )
            for index, item in enumerate(raw_steps)
        )
        return GenerationIncidentRemediation(
            remediation_id=str(row["remediation_id"]),
            incident_id=str(row["incident_id"]),
            runbook_id=row["runbook_id"],
            runbook_name=str(row["runbook_name"]),
            status=str(row["status"]),
            steps=steps,
            actor=row["actor"],
            started_at=str(row["started_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _incident_sla_policy_from_row(row) -> GenerationIncidentSlaPolicy:
        return GenerationIncidentSlaPolicy(
            project_id=row["project_id"],
            enabled=bool(row["enabled"]),
            critical_response_minutes=int(row["critical_response_minutes"] or 15),
            critical_resolution_minutes=int(row["critical_resolution_minutes"] or 240),
            warning_response_minutes=int(row["warning_response_minutes"] or 60),
            warning_resolution_minutes=int(row["warning_resolution_minutes"] or 1440),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _incident_update_from_row(row) -> GenerationIncidentUpdate:
        return GenerationIncidentUpdate(
            update_id=str(row["update_id"]),
            incident_id=str(row["incident_id"]),
            kind=str(row["kind"]),
            actor=row["actor"],
            message=str(row["message"]),
            created_at=str(row["created_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _batch_session_from_row(row) -> BatchSessionRecord:
        return BatchSessionRecord(
            session_id=str(row["session_id"]),
            project_id=row["project_id"],
            scope=str(row["scope"]),
            provider=str(row["provider"]),
            model=str(row["model"]),
            voice=str(row["voice"]),
            total_jobs=int(row["total_jobs"]),
            completed_jobs=int(row["completed_jobs"]),
            failed_jobs=int(row["failed_jobs"]),
            skipped_jobs=int(row["skipped_jobs"]),
            character_count=int(row["character_count"]),
            report_path=row["report_path"],
            output_path=row["output_path"],
            result=str(row["result"]),
            started_at=str(row["started_at"]),
            finished_at=row["finished_at"],
            elapsed_seconds=float(row["elapsed_seconds"] or 0.0),
            active_seconds=float(row["active_seconds"] or 0.0),
            paused_seconds=float(row["paused_seconds"] or 0.0),
            retry_events=int(row["retry_events"] or 0),
            files_per_minute=float(row["files_per_minute"] or 0.0),
            characters_per_minute=float(row["characters_per_minute"] or 0.0),
            failure_summary=json.loads(row["failure_summary_json"] or "{}"),
            monitor_metrics=json.loads(row["monitor_metrics_json"] or "{}"),
            health_score=float(row["health_score"] or 0.0),
            baseline_session_id=row["baseline_session_id"],
            regression_severity=str(row["regression_severity"] or "insufficient_data"),
            regression_reasons=json.loads(row["regression_reasons_json"] or "[]"),
            baseline_metrics=json.loads(row["baseline_metrics_json"] or "{}"),
            performance_deltas=json.loads(row["performance_deltas_json"] or "{}"),
            alert_fingerprint=row["alert_fingerprint"],
            alert_state=str(row["alert_state"] or "none"),
            alert_notification_id=row["alert_notification_id"],
            alert_created_at=row["alert_created_at"],
            alert_acknowledged_at=row["alert_acknowledged_at"],
            incident_id=row["incident_id"],
            incident_status=str(row["incident_status"] or "none"),
        )

    @staticmethod
    def _slo_policy_key(project_id: int | None) -> str:
        return "global" if project_id is None else f"project:{int(project_id)}"

    def get_reliability_slo_policy(
        self,
        project_id: int | None,
    ) -> GenerationSloPolicy | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_reliability_slo_policies "
                "WHERE policy_key = ?",
                (self._slo_policy_key(project_id),),
            ).fetchone()
        if row is None:
            return None
        return GenerationSloPolicy(
            project_id=row["project_id"],
            enabled=bool(row["enabled"]),
            window_days=int(row["window_days"] or 30),
            minimum_sessions=int(row["minimum_sessions"] or 3),
            target_job_success_rate=float(
                row["target_job_success_rate"]
                if row["target_job_success_rate"] is not None
                else 99.0
            ),
            max_retry_rate=float(
                row["max_retry_rate"] if row["max_retry_rate"] is not None else 5.0
            ),
            max_mtta_minutes=float(row["max_mtta_minutes"] or 60.0),
            max_mttr_minutes=float(row["max_mttr_minutes"] or 480.0),
            max_incident_recurrence_rate=float(
                row["max_incident_recurrence_rate"]
                if row["max_incident_recurrence_rate"] is not None
                else 20.0
            ),
            min_runbook_success_rate=float(
                row["min_runbook_success_rate"]
                if row["min_runbook_success_rate"] is not None
                else 80.0
            ),
            min_corrective_action_completion_rate=float(
                row["min_corrective_action_completion_rate"]
                if row["min_corrective_action_completion_rate"] is not None
                else 90.0
            ),
            warning_burn_rate=float(row["warning_burn_rate"] or 1.0),
            critical_burn_rate=float(row["critical_burn_rate"] or 2.0),
            alert_cooldown_minutes=int(
                row["alert_cooldown_minutes"]
                if row["alert_cooldown_minutes"] is not None
                else 240
            ),
            updated_at=str(row["updated_at"] or ""),
        )

    def save_reliability_slo_policy(self, policy: GenerationSloPolicy) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_reliability_slo_policies(
                    policy_key, project_id, enabled, window_days, minimum_sessions,
                    target_job_success_rate, max_retry_rate, max_mtta_minutes,
                    max_mttr_minutes, max_incident_recurrence_rate,
                    min_runbook_success_rate,
                    min_corrective_action_completion_rate, warning_burn_rate,
                    critical_burn_rate, alert_cooldown_minutes, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    enabled = excluded.enabled,
                    window_days = excluded.window_days,
                    minimum_sessions = excluded.minimum_sessions,
                    target_job_success_rate = excluded.target_job_success_rate,
                    max_retry_rate = excluded.max_retry_rate,
                    max_mtta_minutes = excluded.max_mtta_minutes,
                    max_mttr_minutes = excluded.max_mttr_minutes,
                    max_incident_recurrence_rate =
                        excluded.max_incident_recurrence_rate,
                    min_runbook_success_rate = excluded.min_runbook_success_rate,
                    min_corrective_action_completion_rate =
                        excluded.min_corrective_action_completion_rate,
                    warning_burn_rate = excluded.warning_burn_rate,
                    critical_burn_rate = excluded.critical_burn_rate,
                    alert_cooldown_minutes = excluded.alert_cooldown_minutes,
                    updated_at = excluded.updated_at
                """,
                (
                    self._slo_policy_key(policy.project_id),
                    policy.project_id,
                    int(policy.enabled),
                    int(policy.window_days),
                    int(policy.minimum_sessions),
                    float(policy.target_job_success_rate),
                    float(policy.max_retry_rate),
                    float(policy.max_mtta_minutes),
                    float(policy.max_mttr_minutes),
                    float(policy.max_incident_recurrence_rate),
                    float(policy.min_runbook_success_rate),
                    float(policy.min_corrective_action_completion_rate),
                    float(policy.warning_burn_rate),
                    float(policy.critical_burn_rate),
                    int(policy.alert_cooldown_minutes),
                    policy.updated_at,
                ),
            )

    def add_reliability_snapshot(
        self,
        snapshot: GenerationReliabilitySnapshot,
    ) -> None:
        metrics = {
            key: value
            for key, value in snapshot.__dict__.items()
            if key
            not in {
                "snapshot_id",
                "project_id",
                "period_start",
                "period_end",
                "created_at",
                "state",
                "trend",
                "reasons",
                "provider_metrics",
                "alert_fingerprint",
                "alert_notification_id",
            }
        }
        providers = [item.__dict__ for item in snapshot.provider_metrics]
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO generation_reliability_snapshots(
                    snapshot_id, project_id, period_start, period_end, created_at,
                    state, trend, metrics_json, reasons_json, provider_metrics_json,
                    alert_fingerprint, alert_notification_id
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.project_id,
                    snapshot.period_start,
                    snapshot.period_end,
                    snapshot.created_at,
                    snapshot.state,
                    snapshot.trend,
                    json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                    json.dumps(list(snapshot.reasons), ensure_ascii=False),
                    json.dumps(providers, ensure_ascii=False, sort_keys=True),
                    snapshot.alert_fingerprint,
                    snapshot.alert_notification_id,
                ),
            )

    def attach_reliability_snapshot_notification(
        self,
        snapshot_id: str,
        notification_id: str,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE generation_reliability_snapshots "
                "SET alert_notification_id = ? WHERE snapshot_id = ?",
                (notification_id, snapshot_id),
            )

    def has_recent_reliability_alert(self, fingerprint: str, since: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM generation_reliability_snapshots
                WHERE alert_fingerprint = ?
                  AND alert_notification_id IS NOT NULL
                  AND created_at >= ?
                LIMIT 1
                """,
                (fingerprint, since),
            ).fetchone()
        return row is not None

    def list_reliability_snapshots(
        self,
        *,
        project_id: int | None = None,
        limit: int = 100,
    ) -> list[GenerationReliabilitySnapshot]:
        if project_id is None:
            where = "project_id IS NULL"
            params: tuple[object, ...] = (max(1, int(limit)),)
        else:
            where = "project_id = ?"
            params = (project_id, max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_reliability_snapshots "
                f"WHERE {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._reliability_snapshot_from_row(row) for row in rows]

    def list_batch_sessions_between(
        self,
        *,
        project_id: int | None,
        started_at: str,
        finished_before: str,
        limit: int = 100000,
    ) -> list[BatchSessionRecord]:
        conditions = ["started_at >= ?", "started_at < ?"]
        params: list[object] = [started_at, finished_before]
        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)
        params.append(max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM batch_sessions WHERE {' AND '.join(conditions)} "
                "ORDER BY started_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self._batch_session_from_row(row) for row in rows]

    @staticmethod
    def _reliability_snapshot_from_row(row) -> GenerationReliabilitySnapshot:
        metrics = json.loads(row["metrics_json"] or "{}")
        providers = tuple(
            GenerationProviderReliability(**item)
            for item in json.loads(row["provider_metrics_json"] or "[]")
        )
        allowed = GenerationReliabilitySnapshot.__dataclass_fields__
        payload = {key: value for key, value in metrics.items() if key in allowed}
        return GenerationReliabilitySnapshot(
            snapshot_id=str(row["snapshot_id"]),
            project_id=row["project_id"],
            period_start=str(row["period_start"]),
            period_end=str(row["period_end"]),
            created_at=str(row["created_at"]),
            state=str(row["state"] or "insufficient_data"),
            trend=str(row["trend"] or "unknown"),
            reasons=tuple(str(value) for value in json.loads(row["reasons_json"] or "[]")),
            provider_metrics=providers,
            alert_fingerprint=row["alert_fingerprint"],
            alert_notification_id=row["alert_notification_id"],
            **payload,
        )

    @staticmethod
    def _cost_policy_key(project_id: int | None) -> str:
        return "global" if project_id is None else f"project:{project_id}"

    @staticmethod
    def _pricing_rate_key(
        project_id: int | None,
        provider: str,
        model: str,
    ) -> str:
        scope = "global" if project_id is None else f"project:{project_id}"
        return f"{scope}:{provider.strip().casefold()}:{(model or '*').strip().casefold()}"

    def get_cost_budget_policy(
        self,
        project_id: int | None,
    ) -> GenerationCostBudgetPolicy | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_cost_budget_policies WHERE policy_key = ?",
                (self._cost_policy_key(project_id),),
            ).fetchone()
        if row is None:
            return None
        return GenerationCostBudgetPolicy(
            project_id=row["project_id"],
            enabled=bool(row["enabled"]),
            currency=str(row["currency"] or "USD"),
            daily_budget=float(row["daily_budget"] or 0.0),
            weekly_budget=float(row["weekly_budget"] or 0.0),
            monthly_budget=float(row["monthly_budget"] or 0.0),
            warning_percent=float(
                row["warning_percent"]
                if row["warning_percent"] is not None
                else 80.0
            ),
            max_queue_cost=float(row["max_queue_cost"] or 0.0),
            default_price_per_million_characters=float(
                row["default_price_per_million_characters"] or 0.0
            ),
            bill_retry_characters=bool(row["bill_retry_characters"]),
            alert_cooldown_minutes=int(
                row["alert_cooldown_minutes"]
                if row["alert_cooldown_minutes"] is not None
                else 240
            ),
            updated_at=str(row["updated_at"] or ""),
        )

    def save_cost_budget_policy(self, policy: GenerationCostBudgetPolicy) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_cost_budget_policies(
                    policy_key, project_id, enabled, currency, daily_budget,
                    weekly_budget, monthly_budget, warning_percent, max_queue_cost,
                    default_price_per_million_characters, bill_retry_characters,
                    alert_cooldown_minutes, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    enabled = excluded.enabled,
                    currency = excluded.currency,
                    daily_budget = excluded.daily_budget,
                    weekly_budget = excluded.weekly_budget,
                    monthly_budget = excluded.monthly_budget,
                    warning_percent = excluded.warning_percent,
                    max_queue_cost = excluded.max_queue_cost,
                    default_price_per_million_characters =
                        excluded.default_price_per_million_characters,
                    bill_retry_characters = excluded.bill_retry_characters,
                    alert_cooldown_minutes = excluded.alert_cooldown_minutes,
                    updated_at = excluded.updated_at
                """,
                (
                    self._cost_policy_key(policy.project_id),
                    policy.project_id,
                    int(policy.enabled),
                    policy.currency,
                    float(policy.daily_budget),
                    float(policy.weekly_budget),
                    float(policy.monthly_budget),
                    float(policy.warning_percent),
                    float(policy.max_queue_cost),
                    float(policy.default_price_per_million_characters),
                    int(policy.bill_retry_characters),
                    int(policy.alert_cooldown_minutes),
                    policy.updated_at,
                ),
            )

    def save_pricing_rate(self, rate: GenerationPricingRate) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_pricing_rates(
                    rate_id, rate_key, project_id, provider, model,
                    price_per_million_characters, currency, source,
                    effective_from, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rate_key) DO UPDATE SET
                    rate_id = excluded.rate_id,
                    project_id = excluded.project_id,
                    provider = excluded.provider,
                    model = excluded.model,
                    price_per_million_characters =
                        excluded.price_per_million_characters,
                    currency = excluded.currency,
                    source = excluded.source,
                    effective_from = excluded.effective_from,
                    updated_at = excluded.updated_at
                """,
                (
                    rate.rate_id,
                    self._pricing_rate_key(rate.project_id, rate.provider, rate.model),
                    rate.project_id,
                    rate.provider,
                    rate.model or "*",
                    float(rate.price_per_million_characters),
                    rate.currency,
                    rate.source,
                    rate.effective_from,
                    rate.updated_at,
                ),
            )

    def delete_pricing_rate(self, rate_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM generation_pricing_rates WHERE rate_id = ?",
                (rate_id,),
            )

    def list_pricing_rates(
        self,
        *,
        project_id: int | None = None,
        include_global: bool = True,
    ) -> list[GenerationPricingRate]:
        if project_id is None:
            where = "project_id IS NULL"
            params: tuple[object, ...] = ()
        elif include_global:
            where = "project_id = ? OR project_id IS NULL"
            params = (project_id,)
        else:
            where = "project_id = ?"
            params = (project_id,)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_pricing_rates WHERE {where} "
                "ORDER BY project_id IS NULL, provider, model",
                params,
            ).fetchall()
        return [
            GenerationPricingRate(
                rate_id=str(row["rate_id"]),
                project_id=row["project_id"],
                provider=str(row["provider"]),
                model=str(row["model"] or "*"),
                price_per_million_characters=float(
                    row["price_per_million_characters"] or 0.0
                ),
                currency=str(row["currency"] or "USD"),
                source=str(row["source"] or "manual"),
                effective_from=str(row["effective_from"] or ""),
                updated_at=str(row["updated_at"] or ""),
            )
            for row in rows
        ]

    def save_session_cost(self, cost: GenerationSessionCost) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_session_costs(
                    session_id, project_id, provider, model, currency,
                    character_count, retry_characters, billable_characters,
                    price_per_million_characters, estimated_cost, actual_cost,
                    cost_source, recorded_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    provider = excluded.provider,
                    model = excluded.model,
                    currency = excluded.currency,
                    character_count = excluded.character_count,
                    retry_characters = excluded.retry_characters,
                    billable_characters = excluded.billable_characters,
                    price_per_million_characters =
                        excluded.price_per_million_characters,
                    estimated_cost = excluded.estimated_cost,
                    actual_cost = COALESCE(excluded.actual_cost, actual_cost),
                    cost_source = excluded.cost_source,
                    recorded_at = excluded.recorded_at
                """,
                (
                    cost.session_id,
                    cost.project_id,
                    cost.provider,
                    cost.model,
                    cost.currency,
                    int(cost.character_count),
                    int(cost.retry_characters),
                    int(cost.billable_characters),
                    float(cost.price_per_million_characters),
                    float(cost.estimated_cost),
                    cost.actual_cost,
                    cost.cost_source,
                    cost.recorded_at,
                ),
            )

    def get_session_cost(self, session_id: str) -> GenerationSessionCost | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_session_costs WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._session_cost_from_row(row) if row is not None else None

    def list_session_costs(
        self,
        *,
        project_id: int | None = None,
        recorded_at: str | None = None,
        recorded_before: str | None = None,
        limit: int = 1000,
    ) -> list[GenerationSessionCost]:
        conditions: list[str] = []
        params: list[object] = []
        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)
        if recorded_at is not None:
            conditions.append("recorded_at >= ?")
            params.append(recorded_at)
        if recorded_before is not None:
            conditions.append("recorded_at < ?")
            params.append(recorded_before)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_session_costs {where} "
                "ORDER BY recorded_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self._session_cost_from_row(row) for row in rows]

    def add_cost_capacity_snapshot(
        self,
        snapshot: GenerationCostCapacitySnapshot,
    ) -> None:
        metrics = {
            key: value
            for key, value in snapshot.__dict__.items()
            if key
            not in {
                "snapshot_id",
                "project_id",
                "period_start",
                "period_end",
                "created_at",
                "currency",
                "state",
                "reasons",
                "queue_forecast",
                "provider_metrics",
                "alert_fingerprint",
                "alert_notification_id",
            }
        }
        queue_forecast = (
            snapshot.queue_forecast.__dict__
            if snapshot.queue_forecast is not None
            else {}
        )
        provider_metrics = [item.__dict__ for item in snapshot.provider_metrics]
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO generation_cost_capacity_snapshots(
                    snapshot_id, project_id, period_start, period_end, created_at,
                    currency, state, metrics_json, reasons_json,
                    queue_forecast_json, provider_metrics_json,
                    alert_fingerprint, alert_notification_id
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.project_id,
                    snapshot.period_start,
                    snapshot.period_end,
                    snapshot.created_at,
                    snapshot.currency,
                    snapshot.state,
                    json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                    json.dumps(list(snapshot.reasons), ensure_ascii=False),
                    json.dumps(queue_forecast, ensure_ascii=False, sort_keys=True),
                    json.dumps(provider_metrics, ensure_ascii=False, sort_keys=True),
                    snapshot.alert_fingerprint,
                    snapshot.alert_notification_id,
                ),
            )

    def attach_cost_snapshot_notification(
        self,
        snapshot_id: str,
        notification_id: str,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE generation_cost_capacity_snapshots "
                "SET alert_notification_id = ? WHERE snapshot_id = ?",
                (notification_id, snapshot_id),
            )

    def has_recent_cost_alert(self, fingerprint: str, since: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM generation_cost_capacity_snapshots
                WHERE alert_fingerprint = ?
                  AND alert_notification_id IS NOT NULL
                  AND created_at >= ?
                LIMIT 1
                """,
                (fingerprint, since),
            ).fetchone()
        return row is not None

    def list_cost_capacity_snapshots(
        self,
        *,
        project_id: int | None = None,
        limit: int = 100,
    ) -> list[GenerationCostCapacitySnapshot]:
        if project_id is None:
            where = "project_id IS NULL"
            params: tuple[object, ...] = (max(1, int(limit)),)
        else:
            where = "project_id = ?"
            params = (project_id, max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM generation_cost_capacity_snapshots "
                f"WHERE {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._cost_snapshot_from_row(row) for row in rows]

    @staticmethod
    def _session_cost_from_row(row) -> GenerationSessionCost:
        return GenerationSessionCost(
            session_id=str(row["session_id"]),
            project_id=row["project_id"],
            provider=str(row["provider"]),
            model=str(row["model"]),
            currency=str(row["currency"] or "USD"),
            character_count=int(row["character_count"] or 0),
            retry_characters=int(row["retry_characters"] or 0),
            billable_characters=int(row["billable_characters"] or 0),
            price_per_million_characters=float(
                row["price_per_million_characters"] or 0.0
            ),
            estimated_cost=float(row["estimated_cost"] or 0.0),
            actual_cost=(
                float(row["actual_cost"])
                if row["actual_cost"] is not None
                else None
            ),
            cost_source=str(row["cost_source"] or "estimated"),
            recorded_at=str(row["recorded_at"] or ""),
        )

    @staticmethod
    def _cost_snapshot_from_row(row) -> GenerationCostCapacitySnapshot:
        metrics = json.loads(row["metrics_json"] or "{}")
        forecast_data = json.loads(row["queue_forecast_json"] or "{}")
        provider_data = json.loads(row["provider_metrics_json"] or "[]")
        forecast = (
            GenerationCapacityForecast(**forecast_data)
            if forecast_data
            else None
        )
        providers = tuple(
            GenerationProviderCostEfficiency(**item) for item in provider_data
        )
        allowed = GenerationCostCapacitySnapshot.__dataclass_fields__
        payload = {key: value for key, value in metrics.items() if key in allowed}
        return GenerationCostCapacitySnapshot(
            snapshot_id=str(row["snapshot_id"]),
            project_id=row["project_id"],
            period_start=str(row["period_start"]),
            period_end=str(row["period_end"]),
            created_at=str(row["created_at"]),
            currency=str(row["currency"] or "USD"),
            state=str(row["state"] or "healthy"),
            reasons=tuple(str(item) for item in json.loads(row["reasons_json"] or "[]")),
            queue_forecast=forecast,
            provider_metrics=providers,
            alert_fingerprint=row["alert_fingerprint"],
            alert_notification_id=row["alert_notification_id"],
            **payload,
        )

