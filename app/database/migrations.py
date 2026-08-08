from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.database.schema import INITIAL_SCHEMA_SQL

Migration = tuple[int, str]
MULTI_SOURCE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS project_sources (
    source_id TEXT PRIMARY KEY,
    project_id INTEGER,
    display_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_path TEXT NOT NULL,
    worksheet_name TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    import_order INTEGER NOT NULL DEFAULT 0,
    detected_encoding TEXT,
    detected_delimiter TEXT,
    text_column TEXT NOT NULL DEFAULT 'text',
    filename_column TEXT NOT NULL DEFAULT 'filename',
    voice_column TEXT,
    model_column TEXT,
    language_column TEXT,
    output_subfolder_column TEXT,
    row_start INTEGER NOT NULL DEFAULT 2,
    row_end INTEGER,
    imported_at TEXT,
    last_modified TEXT,
    source_hash TEXT,
    import_status TEXT NOT NULL DEFAULT 'ready',
    valid_rows INTEGER NOT NULL DEFAULT 0,
    rejected_rows INTEGER NOT NULL DEFAULT 0,
    issue_count INTEGER NOT NULL DEFAULT 0,
    settings_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS source_worksheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    worksheet_name TEXT NOT NULL,
    worksheet_order INTEGER NOT NULL DEFAULT 0,
    selected INTEGER NOT NULL DEFAULT 1,
    header_json TEXT NOT NULL DEFAULT '[]',
    preview_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY(source_id) REFERENCES project_sources(source_id) ON DELETE CASCADE,
    UNIQUE(source_id, worksheet_name)
);

CREATE TABLE IF NOT EXISTS source_import_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_hash TEXT,
    FOREIGN KEY(source_id) REFERENCES project_sources(source_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS provider_profiles (
    profile_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    display_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 0,
    safe_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    job_id INTEGER,
    provider TEXT NOT NULL,
    profile_id TEXT,
    request_id TEXT,
    usage_amount REAL,
    usage_unit TEXT,
    estimated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
);

ALTER TABLE jobs ADD COLUMN source_id TEXT;
ALTER TABLE jobs ADD COLUMN source_display_name TEXT;
ALTER TABLE jobs ADD COLUMN source_sheet TEXT;
ALTER TABLE jobs ADD COLUMN source_row INTEGER;
ALTER TABLE jobs ADD COLUMN provider_override TEXT;
ALTER TABLE jobs ADD COLUMN account_profile_override TEXT;
ALTER TABLE jobs ADD COLUMN voice_override TEXT;
ALTER TABLE jobs ADD COLUMN model_override TEXT;
ALTER TABLE jobs ADD COLUMN language_override TEXT;
ALTER TABLE jobs ADD COLUMN output_subfolder TEXT;

CREATE INDEX IF NOT EXISTS idx_project_sources_project_order ON project_sources(project_id, import_order);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(project_id, source_id);
CREATE INDEX IF NOT EXISTS idx_provider_usage_project ON provider_usage(project_id, provider, created_at);
"""

PRODUCT_POLISH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0,
    action_label TEXT,
    action_payload TEXT
);

CREATE TABLE IF NOT EXISTS activity_timeline (
    event_id TEXT PRIMARY KEY,
    project_id INTEGER,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS batch_sessions (
    session_id TEXT PRIMARY KEY,
    project_id INTEGER,
    scope TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    voice TEXT NOT NULL,
    total_jobs INTEGER NOT NULL DEFAULT 0,
    completed_jobs INTEGER NOT NULL DEFAULT 0,
    failed_jobs INTEGER NOT NULL DEFAULT 0,
    skipped_jobs INTEGER NOT NULL DEFAULT 0,
    character_count INTEGER NOT NULL DEFAULT 0,
    report_path TEXT,
    output_path TEXT,
    result TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS workspace_preferences (
    preference_id TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_level_settings (
    source_id TEXT PRIMARY KEY,
    provider TEXT,
    account_profile_id TEXT,
    model_id TEXT,
    voice_id TEXT,
    language_code TEXT,
    output_format TEXT,
    options_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES project_sources(source_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notifications_read_created ON notifications(read, created_at);
CREATE INDEX IF NOT EXISTS idx_activity_project_created ON activity_timeline(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_batch_sessions_project_started ON batch_sessions(project_id, started_at);
"""


GENERATION_RETRY_SCHEMA_SQL = """
ALTER TABLE jobs ADD COLUMN failure_category TEXT;
ALTER TABLE jobs ADD COLUMN error_code TEXT;
ALTER TABLE jobs ADD COLUMN error_fingerprint TEXT;
ALTER TABLE jobs ADD COLUMN retryable INTEGER;
ALTER TABLE jobs ADD COLUMN retry_exhausted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN next_retry_at TEXT;
ALTER TABLE jobs ADD COLUMN retry_history_json TEXT NOT NULL DEFAULT '[]';

CREATE INDEX IF NOT EXISTS idx_jobs_failure_category ON jobs(project_id, failure_category);
CREATE INDEX IF NOT EXISTS idx_jobs_error_fingerprint ON jobs(project_id, error_fingerprint);
"""


GENERATION_HISTORY_SCHEMA_SQL = """
ALTER TABLE batch_sessions ADD COLUMN elapsed_seconds REAL NOT NULL DEFAULT 0;
ALTER TABLE batch_sessions ADD COLUMN active_seconds REAL NOT NULL DEFAULT 0;
ALTER TABLE batch_sessions ADD COLUMN paused_seconds REAL NOT NULL DEFAULT 0;
ALTER TABLE batch_sessions ADD COLUMN retry_events INTEGER NOT NULL DEFAULT 0;
ALTER TABLE batch_sessions ADD COLUMN files_per_minute REAL NOT NULL DEFAULT 0;
ALTER TABLE batch_sessions ADD COLUMN characters_per_minute REAL NOT NULL DEFAULT 0;
ALTER TABLE batch_sessions ADD COLUMN failure_summary_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE batch_sessions ADD COLUMN monitor_metrics_json TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_batch_sessions_provider_started
    ON batch_sessions(provider, started_at);
CREATE INDEX IF NOT EXISTS idx_batch_sessions_result_started
    ON batch_sessions(result, started_at);
"""


GENERATION_PERFORMANCE_SCHEMA_SQL = """
ALTER TABLE batch_sessions ADD COLUMN health_score REAL NOT NULL DEFAULT 0;
ALTER TABLE batch_sessions ADD COLUMN baseline_session_id TEXT;
ALTER TABLE batch_sessions ADD COLUMN regression_severity TEXT NOT NULL DEFAULT 'insufficient_data';
ALTER TABLE batch_sessions ADD COLUMN regression_reasons_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE batch_sessions ADD COLUMN baseline_metrics_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE batch_sessions ADD COLUMN performance_deltas_json TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_batch_sessions_regression_started
    ON batch_sessions(regression_severity, started_at);
CREATE INDEX IF NOT EXISTS idx_batch_sessions_health_started
    ON batch_sessions(health_score, started_at);
"""


GENERATION_PERFORMANCE_POLICY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_performance_budgets (
    budget_key TEXT PRIMARY KEY,
    project_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    thresholds_json TEXT NOT NULL DEFAULT '{}',
    alert_cooldown_minutes INTEGER NOT NULL DEFAULT 60,
    silence_until TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

ALTER TABLE batch_sessions ADD COLUMN alert_fingerprint TEXT;
ALTER TABLE batch_sessions ADD COLUMN alert_state TEXT NOT NULL DEFAULT 'none';
ALTER TABLE batch_sessions ADD COLUMN alert_notification_id TEXT;
ALTER TABLE batch_sessions ADD COLUMN alert_created_at TEXT;
ALTER TABLE batch_sessions ADD COLUMN alert_acknowledged_at TEXT;

CREATE INDEX IF NOT EXISTS idx_performance_budgets_project
    ON generation_performance_budgets(project_id);
CREATE INDEX IF NOT EXISTS idx_batch_sessions_alert_state_started
    ON batch_sessions(alert_state, started_at);
CREATE INDEX IF NOT EXISTS idx_batch_sessions_alert_fingerprint_created
    ON batch_sessions(alert_fingerprint, alert_created_at);
"""


GENERATION_INCIDENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_incidents (
    incident_id TEXT PRIMARY KEY,
    project_id INTEGER,
    alert_fingerprint TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    first_session_id TEXT NOT NULL,
    latest_session_id TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    session_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    acknowledged_at TEXT,
    resolved_at TEXT,
    resolution_note TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY(first_session_id) REFERENCES batch_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY(latest_session_id) REFERENCES batch_sessions(session_id) ON DELETE CASCADE
);

ALTER TABLE batch_sessions ADD COLUMN incident_id TEXT;
ALTER TABLE batch_sessions ADD COLUMN incident_status TEXT NOT NULL DEFAULT 'none';

CREATE INDEX IF NOT EXISTS idx_generation_incidents_project_status
    ON generation_incidents(project_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_generation_incidents_fingerprint_status
    ON generation_incidents(alert_fingerprint, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_batch_sessions_incident
    ON batch_sessions(incident_id, started_at);
"""


GENERATION_INCIDENT_SLA_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_incident_sla_policies (
    policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    critical_response_minutes INTEGER NOT NULL DEFAULT 15,
    critical_resolution_minutes INTEGER NOT NULL DEFAULT 240,
    warning_response_minutes INTEGER NOT NULL DEFAULT 60,
    warning_resolution_minutes INTEGER NOT NULL DEFAULT 1440,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_incident_updates (
    update_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT,
    message TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(incident_id) REFERENCES generation_incidents(incident_id) ON DELETE CASCADE
);

ALTER TABLE generation_incidents ADD COLUMN assigned_to TEXT;
ALTER TABLE generation_incidents ADD COLUMN priority TEXT NOT NULL DEFAULT 'p1';
ALTER TABLE generation_incidents ADD COLUMN response_due_at TEXT;
ALTER TABLE generation_incidents ADD COLUMN resolution_due_at TEXT;
ALTER TABLE generation_incidents ADD COLUMN sla_state TEXT NOT NULL DEFAULT 'not_configured';
ALTER TABLE generation_incidents ADD COLUMN escalation_level INTEGER NOT NULL DEFAULT 0;
ALTER TABLE generation_incidents ADD COLUMN escalated_at TEXT;
ALTER TABLE generation_incidents ADD COLUMN last_sla_notification_level INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_incident_sla_policy_project
    ON generation_incident_sla_policies(project_id);
CREATE INDEX IF NOT EXISTS idx_incident_updates_incident_created
    ON generation_incident_updates(incident_id, created_at);
CREATE INDEX IF NOT EXISTS idx_generation_incidents_sla_state
    ON generation_incidents(sla_state, status, resolution_due_at);
CREATE INDEX IF NOT EXISTS idx_generation_incidents_assignee
    ON generation_incidents(assigned_to, status, updated_at);
"""


GENERATION_INCIDENT_RUNBOOK_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_incident_runbooks (
    runbook_id TEXT PRIMARY KEY,
    project_id INTEGER,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    severity_filter TEXT NOT NULL DEFAULT 'any',
    fingerprint_pattern TEXT NOT NULL DEFAULT '',
    steps_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_incident_remediations (
    remediation_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    runbook_id TEXT,
    runbook_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    steps_json TEXT NOT NULL DEFAULT '[]',
    actor TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(incident_id) REFERENCES generation_incidents(incident_id) ON DELETE CASCADE,
    FOREIGN KEY(runbook_id) REFERENCES generation_incident_runbooks(runbook_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_incident_runbooks_project_enabled
    ON generation_incident_runbooks(project_id, enabled, updated_at);
CREATE INDEX IF NOT EXISTS idx_incident_remediations_incident_status
    ON generation_incident_remediations(incident_id, status, updated_at);
"""


GENERATION_INCIDENT_REVIEW_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_incident_reviews (
    review_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'draft',
    impact_summary TEXT NOT NULL DEFAULT '',
    root_cause_category TEXT NOT NULL DEFAULT 'unknown',
    root_cause TEXT NOT NULL DEFAULT '',
    contributing_factors_json TEXT NOT NULL DEFAULT '[]',
    detection_gap TEXT NOT NULL DEFAULT '',
    resolution_summary TEXT NOT NULL DEFAULT '',
    lessons_learned TEXT NOT NULL DEFAULT '',
    reviewer TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(incident_id) REFERENCES generation_incidents(incident_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_incident_action_items (
    action_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'p2',
    owner TEXT,
    due_at TEXT,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    overdue_notified_at TEXT,
    FOREIGN KEY(review_id) REFERENCES generation_incident_reviews(review_id) ON DELETE CASCADE,
    FOREIGN KEY(incident_id) REFERENCES generation_incidents(incident_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_incident_reviews_status_updated
    ON generation_incident_reviews(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_incident_actions_incident_status
    ON generation_incident_action_items(incident_id, status, due_at);
CREATE INDEX IF NOT EXISTS idx_incident_actions_owner_status
    ON generation_incident_action_items(owner, status, due_at);
"""


GENERATION_PROBLEM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_known_problems (
    problem_id TEXT PRIMARY KEY,
    project_id INTEGER,
    problem_key TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'investigating',
    severity TEXT NOT NULL DEFAULT 'critical',
    root_cause_category TEXT NOT NULL DEFAULT 'unknown',
    workaround TEXT NOT NULL DEFAULT '',
    permanent_fix TEXT NOT NULL DEFAULT '',
    owner TEXT,
    fingerprints_json TEXT NOT NULL DEFAULT '[]',
    incident_ids_json TEXT NOT NULL DEFAULT '[]',
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    monitoring_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS generation_problem_incidents (
    problem_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    match_reason TEXT NOT NULL DEFAULT 'manual',
    linked_at TEXT NOT NULL,
    PRIMARY KEY(problem_id, incident_id),
    FOREIGN KEY(problem_id) REFERENCES generation_known_problems(problem_id) ON DELETE CASCADE,
    FOREIGN KEY(incident_id) REFERENCES generation_incidents(incident_id) ON DELETE CASCADE
);

ALTER TABLE generation_incidents ADD COLUMN problem_id TEXT;
ALTER TABLE generation_incidents ADD COLUMN problem_status TEXT NOT NULL DEFAULT 'none';
ALTER TABLE generation_incident_action_items ADD COLUMN problem_id TEXT;

CREATE INDEX IF NOT EXISTS idx_generation_problems_project_status
    ON generation_known_problems(project_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_generation_problems_key
    ON generation_known_problems(problem_key, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_problem_incidents_incident
    ON generation_problem_incidents(incident_id, linked_at);
CREATE INDEX IF NOT EXISTS idx_generation_incidents_problem
    ON generation_incidents(problem_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_incident_actions_problem_status
    ON generation_incident_action_items(problem_id, status, due_at);
"""


GENERATION_AUTOMATED_REMEDIATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_remediation_automation_policies (
    policy_key TEXT PRIMARY KEY,
    project_id INTEGER UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 0,
    dry_run_default INTEGER NOT NULL DEFAULT 1,
    allowed_actions_json TEXT NOT NULL DEFAULT '[]',
    require_confirmation_for_mutating INTEGER NOT NULL DEFAULT 1,
    allow_unattended_mutating INTEGER NOT NULL DEFAULT 0,
    max_auto_runs_per_incident INTEGER NOT NULL DEFAULT 2,
    cooldown_minutes INTEGER NOT NULL DEFAULT 60,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_automated_remediations (
    automation_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    problem_id TEXT,
    runbook_id TEXT,
    runbook_name TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'running',
    dry_run INTEGER NOT NULL DEFAULT 1,
    action_results_json TEXT NOT NULL DEFAULT '[]',
    actor TEXT,
    blocked_reason TEXT,
    rollback_status TEXT NOT NULL DEFAULT 'not_requested',
    rollback_note TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(incident_id) REFERENCES generation_incidents(incident_id) ON DELETE CASCADE,
    FOREIGN KEY(problem_id) REFERENCES generation_known_problems(problem_id) ON DELETE SET NULL,
    FOREIGN KEY(runbook_id) REFERENCES generation_incident_runbooks(runbook_id) ON DELETE SET NULL
);

ALTER TABLE generation_incident_runbooks ADD COLUMN automation_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE generation_incident_runbooks ADD COLUMN automation_trigger TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE generation_incident_runbooks ADD COLUMN automation_actions_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE generation_incident_runbooks ADD COLUMN dry_run_only INTEGER NOT NULL DEFAULT 1;
ALTER TABLE generation_incident_runbooks ADD COLUMN max_auto_runs INTEGER NOT NULL DEFAULT 1;
ALTER TABLE generation_incident_runbooks ADD COLUMN cooldown_minutes INTEGER NOT NULL DEFAULT 60;
ALTER TABLE generation_incident_runbooks ADD COLUMN rollback_instructions TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_remediation_automation_policy_project
    ON generation_remediation_automation_policies(project_id);
CREATE INDEX IF NOT EXISTS idx_automated_remediations_incident_started
    ON generation_automated_remediations(incident_id, started_at);
CREATE INDEX IF NOT EXISTS idx_automated_remediations_runbook_trigger
    ON generation_automated_remediations(runbook_id, trigger, started_at);
CREATE INDEX IF NOT EXISTS idx_automated_remediations_status
    ON generation_automated_remediations(status, updated_at);
"""


GENERATION_RELIABILITY_SLO_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_reliability_slo_policies (
    policy_key TEXT PRIMARY KEY,
    project_id INTEGER UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    window_days INTEGER NOT NULL DEFAULT 30,
    minimum_sessions INTEGER NOT NULL DEFAULT 3,
    target_job_success_rate REAL NOT NULL DEFAULT 99.0,
    max_retry_rate REAL NOT NULL DEFAULT 5.0,
    max_mtta_minutes REAL NOT NULL DEFAULT 60.0,
    max_mttr_minutes REAL NOT NULL DEFAULT 480.0,
    max_incident_recurrence_rate REAL NOT NULL DEFAULT 20.0,
    min_runbook_success_rate REAL NOT NULL DEFAULT 80.0,
    min_corrective_action_completion_rate REAL NOT NULL DEFAULT 90.0,
    warning_burn_rate REAL NOT NULL DEFAULT 1.0,
    critical_burn_rate REAL NOT NULL DEFAULT 2.0,
    alert_cooldown_minutes INTEGER NOT NULL DEFAULT 240,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_reliability_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    project_id INTEGER,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'insufficient_data',
    trend TEXT NOT NULL DEFAULT 'unknown',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    reasons_json TEXT NOT NULL DEFAULT '[]',
    provider_metrics_json TEXT NOT NULL DEFAULT '[]',
    alert_fingerprint TEXT,
    alert_notification_id TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reliability_slo_policy_project
    ON generation_reliability_slo_policies(project_id);
CREATE INDEX IF NOT EXISTS idx_reliability_snapshots_project_created
    ON generation_reliability_snapshots(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reliability_snapshots_state_created
    ON generation_reliability_snapshots(state, created_at);
CREATE INDEX IF NOT EXISTS idx_reliability_snapshots_alert
    ON generation_reliability_snapshots(alert_fingerprint, created_at);
"""


GENERATION_COST_CAPACITY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_cost_budget_policies (
    policy_key TEXT PRIMARY KEY,
    project_id INTEGER UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    currency TEXT NOT NULL DEFAULT 'USD',
    daily_budget REAL NOT NULL DEFAULT 0.0,
    weekly_budget REAL NOT NULL DEFAULT 0.0,
    monthly_budget REAL NOT NULL DEFAULT 0.0,
    warning_percent REAL NOT NULL DEFAULT 80.0,
    max_queue_cost REAL NOT NULL DEFAULT 0.0,
    default_price_per_million_characters REAL NOT NULL DEFAULT 0.0,
    bill_retry_characters INTEGER NOT NULL DEFAULT 1,
    alert_cooldown_minutes INTEGER NOT NULL DEFAULT 240,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_pricing_rates (
    rate_id TEXT PRIMARY KEY,
    rate_key TEXT NOT NULL UNIQUE,
    project_id INTEGER,
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '*',
    price_per_million_characters REAL NOT NULL DEFAULT 0.0,
    currency TEXT NOT NULL DEFAULT 'USD',
    source TEXT NOT NULL DEFAULT 'manual',
    effective_from TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_session_costs (
    session_id TEXT PRIMARY KEY,
    project_id INTEGER,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    character_count INTEGER NOT NULL DEFAULT 0,
    retry_characters INTEGER NOT NULL DEFAULT 0,
    billable_characters INTEGER NOT NULL DEFAULT 0,
    price_per_million_characters REAL NOT NULL DEFAULT 0.0,
    estimated_cost REAL NOT NULL DEFAULT 0.0,
    actual_cost REAL,
    cost_source TEXT NOT NULL DEFAULT 'estimated',
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES batch_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS generation_cost_capacity_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    project_id INTEGER,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    created_at TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    state TEXT NOT NULL DEFAULT 'healthy',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    reasons_json TEXT NOT NULL DEFAULT '[]',
    queue_forecast_json TEXT NOT NULL DEFAULT '{}',
    provider_metrics_json TEXT NOT NULL DEFAULT '[]',
    alert_fingerprint TEXT,
    alert_notification_id TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_generation_cost_policy_project
    ON generation_cost_budget_policies(project_id);
CREATE INDEX IF NOT EXISTS idx_generation_pricing_project_provider_model
    ON generation_pricing_rates(project_id, provider, model);
CREATE INDEX IF NOT EXISTS idx_generation_session_costs_project_recorded
    ON generation_session_costs(project_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_generation_session_costs_provider_model
    ON generation_session_costs(provider, model, recorded_at);
CREATE INDEX IF NOT EXISTS idx_generation_cost_snapshots_project_created
    ON generation_cost_capacity_snapshots(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_generation_cost_snapshots_alert
    ON generation_cost_capacity_snapshots(alert_fingerprint, created_at);
"""


GENERATION_HARDENING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_maintenance_policies (
    policy_key TEXT PRIMARY KEY,
    project_id INTEGER UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    session_retention_days INTEGER NOT NULL DEFAULT 365,
    notification_retention_days INTEGER NOT NULL DEFAULT 90,
    activity_retention_days INTEGER NOT NULL DEFAULT 180,
    snapshot_retention_days INTEGER NOT NULL DEFAULT 180,
    maintenance_run_retention_days INTEGER NOT NULL DEFAULT 365,
    backup_retention_count INTEGER NOT NULL DEFAULT 10,
    run_quick_check_on_startup INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_maintenance_runs (
    run_id TEXT PRIMARY KEY,
    project_id INTEGER,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    artifact_path TEXT,
    artifact_sha256 TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_generation_maintenance_policy_project
    ON generation_maintenance_policies(project_id);
CREATE INDEX IF NOT EXISTS idx_generation_maintenance_runs_project_started
    ON generation_maintenance_runs(project_id, started_at);
CREATE INDEX IF NOT EXISTS idx_generation_maintenance_runs_operation_started
    ON generation_maintenance_runs(operation, started_at);
"""


GENERATION_ORCHESTRATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_orchestration_policies (
    policy_key TEXT PRIMARY KEY,
    project_id INTEGER UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    auto_failover INTEGER NOT NULL DEFAULT 1,
    failure_threshold INTEGER NOT NULL DEFAULT 2,
    circuit_cooldown_seconds INTEGER NOT NULL DEFAULT 300,
    max_switches_per_run INTEGER NOT NULL DEFAULT 2,
    sticky_successful_profile INTEGER NOT NULL DEFAULT 1,
    notify_on_circuit_open INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_provider_circuit_states (
    state_key TEXT PRIMARY KEY,
    project_id INTEGER,
    provider TEXT NOT NULL,
    profile_id TEXT,
    profile_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'closed',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    opened_at TEXT,
    retry_after TEXT,
    last_failure_category TEXT,
    last_failure_code TEXT,
    last_failure_at TEXT,
    last_success_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_failover_events (
    event_id TEXT PRIMARY KEY,
    project_id INTEGER,
    job_row_number INTEGER,
    filename TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    from_profile_id TEXT,
    from_profile_name TEXT NOT NULL DEFAULT '',
    to_profile_id TEXT,
    to_profile_name TEXT,
    failure_category TEXT NOT NULL DEFAULT 'unknown',
    error_code TEXT NOT NULL DEFAULT 'unknown',
    outcome TEXT NOT NULL,
    switch_number INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    circuit_opened INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_orchestration_policy_project
    ON generation_orchestration_policies(project_id);
CREATE INDEX IF NOT EXISTS idx_provider_circuit_project_provider
    ON generation_provider_circuit_states(project_id, provider, status);
CREATE INDEX IF NOT EXISTS idx_failover_events_project_created
    ON generation_failover_events(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_failover_events_provider_outcome
    ON generation_failover_events(provider, outcome, created_at);
"""


GENERATION_ADAPTIVE_ROUTING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_adaptive_routing_policies (
    policy_key TEXT PRIMARY KEY,
    project_id INTEGER UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'priority',
    health_weight REAL NOT NULL DEFAULT 0.45,
    capacity_weight REAL NOT NULL DEFAULT 0.30,
    latency_weight REAL NOT NULL DEFAULT 0.15,
    priority_weight REAL NOT NULL DEFAULT 0.10,
    minimum_quota_reserve INTEGER NOT NULL DEFAULT 0,
    max_profile_share_percent INTEGER NOT NULL DEFAULT 70,
    sample_window INTEGER NOT NULL DEFAULT 50,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_provider_routing_metrics (
    metric_key TEXT PRIMARY KEY,
    project_id INTEGER,
    provider TEXT NOT NULL,
    profile_id TEXT,
    profile_name TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    total_latency_seconds REAL NOT NULL DEFAULT 0.0,
    total_characters INTEGER NOT NULL DEFAULT 0,
    ewma_latency_seconds REAL,
    health_score REAL NOT NULL DEFAULT 85.0,
    last_selected_at TEXT,
    last_success_at TEXT,
    last_failure_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_routing_decisions (
    decision_id TEXT PRIMARY KEY,
    project_id INTEGER,
    job_row_number INTEGER,
    filename TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    profile_id TEXT,
    profile_name TEXT NOT NULL DEFAULT '',
    routing_mode TEXT NOT NULL DEFAULT 'priority',
    routing_score REAL NOT NULL DEFAULT 0.0,
    routing_weight INTEGER NOT NULL DEFAULT 1,
    estimated_characters INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_adaptive_routing_policy_project
    ON generation_adaptive_routing_policies(project_id);
CREATE INDEX IF NOT EXISTS idx_provider_routing_metrics_project_provider
    ON generation_provider_routing_metrics(project_id, provider, health_score);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_project_created
    ON generation_routing_decisions(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_profile_created
    ON generation_routing_decisions(provider, profile_id, created_at);
"""


GENERATION_DYNAMIC_SCHEDULING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_scheduling_policies (
    policy_key TEXT PRIMARY KEY,
    project_id INTEGER UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'adaptive',
    minimum_concurrency INTEGER NOT NULL DEFAULT 1,
    initial_concurrency INTEGER NOT NULL DEFAULT 2,
    maximum_concurrency INTEGER NOT NULL DEFAULT 4,
    per_profile_concurrency INTEGER NOT NULL DEFAULT 2,
    success_window INTEGER NOT NULL DEFAULT 5,
    error_window INTEGER NOT NULL DEFAULT 5,
    increase_step INTEGER NOT NULL DEFAULT 1,
    decrease_factor REAL NOT NULL DEFAULT 0.5,
    rate_limit_cooldown_seconds INTEGER NOT NULL DEFAULT 30,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_provider_throttle_states (
    throttle_key TEXT PRIMARY KEY,
    project_id INTEGER,
    provider TEXT NOT NULL,
    profile_id TEXT,
    profile_name TEXT NOT NULL DEFAULT '',
    current_concurrency INTEGER NOT NULL DEFAULT 1,
    recent_rate_limits INTEGER NOT NULL DEFAULT 0,
    cooldown_until TEXT,
    last_rate_limit_at TEXT,
    last_recovered_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_scheduler_events (
    event_id TEXT PRIMARY KEY,
    project_id INTEGER,
    provider TEXT NOT NULL,
    profile_id TEXT,
    profile_name TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    from_concurrency INTEGER NOT NULL DEFAULT 1,
    to_concurrency INTEGER NOT NULL DEFAULT 1,
    pending_jobs INTEGER NOT NULL DEFAULT 0,
    active_jobs INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduling_policy_project
    ON generation_scheduling_policies(project_id);
CREATE INDEX IF NOT EXISTS idx_provider_throttle_project_provider
    ON generation_provider_throttle_states(project_id, provider, cooldown_until);
CREATE INDEX IF NOT EXISTS idx_scheduler_events_project_created
    ON generation_scheduler_events(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_scheduler_events_profile_created
    ON generation_scheduler_events(provider, profile_id, created_at);
"""


GENERATION_DEADLINE_SCHEDULING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_deadline_scheduling_policies (
    policy_key TEXT PRIMARY KEY,
    project_id INTEGER UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 0,
    target_completion_minutes INTEGER NOT NULL DEFAULT 60,
    warning_slack_minutes INTEGER NOT NULL DEFAULT 15,
    allow_concurrency_boost INTEGER NOT NULL DEFAULT 1,
    maximum_deadline_concurrency INTEGER NOT NULL DEFAULT 8,
    fallback_characters_per_minute INTEGER NOT NULL DEFAULT 1200,
    safety_margin_percent INTEGER NOT NULL DEFAULT 15,
    persist_forecasts INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_queue_forecasts (
    forecast_id TEXT PRIMARY KEY,
    project_id INTEGER,
    provider TEXT NOT NULL,
    job_count INTEGER NOT NULL DEFAULT 0,
    total_characters INTEGER NOT NULL DEFAULT 0,
    current_concurrency INTEGER NOT NULL DEFAULT 1,
    recommended_concurrency INTEGER NOT NULL DEFAULT 1,
    characters_per_minute REAL NOT NULL DEFAULT 0.0,
    estimated_duration_seconds REAL NOT NULL DEFAULT 0.0,
    estimated_finish_at TEXT NOT NULL,
    deadline_at TEXT NOT NULL,
    slack_seconds REAL NOT NULL DEFAULT 0.0,
    risk_score REAL NOT NULL DEFAULT 0.0,
    risk_level TEXT NOT NULL DEFAULT 'insufficient_data',
    recommendation TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'fallback',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_deadline_policy_project
    ON generation_deadline_scheduling_policies(project_id);
CREATE INDEX IF NOT EXISTS idx_queue_forecasts_project_created
    ON generation_queue_forecasts(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_queue_forecasts_risk_created
    ON generation_queue_forecasts(risk_level, created_at);
"""


GENERATION_ORCHESTRATION_UI_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_orchestration_view_preferences (
    preference_key TEXT PRIMARY KEY,
    project_id INTEGER UNIQUE,
    selected_tab INTEGER NOT NULL DEFAULT 0,
    auto_refresh INTEGER NOT NULL DEFAULT 0,
    refresh_interval_seconds INTEGER NOT NULL DEFAULT 10,
    table_density TEXT NOT NULL DEFAULT 'comfortable',
    search_text TEXT NOT NULL DEFAULT '',
    status_filter TEXT NOT NULL DEFAULT 'all',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_orchestration_view_preferences_project
    ON generation_orchestration_view_preferences(project_id);
"""


GENERATION_ORCHESTRATION_WORKFLOW_UI_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation_orchestration_saved_views (
    view_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    project_id INTEGER,
    name TEXT NOT NULL,
    selected_tab INTEGER NOT NULL DEFAULT 0,
    table_density TEXT NOT NULL DEFAULT 'comfortable',
    search_text TEXT NOT NULL DEFAULT '',
    status_filter TEXT NOT NULL DEFAULT 'all',
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(scope_key, name),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_orchestration_operator_actions (
    action_id TEXT PRIMARY KEY,
    project_id INTEGER,
    action_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_count INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_orchestration_saved_views_scope
    ON generation_orchestration_saved_views(scope_key, is_default, updated_at);
CREATE INDEX IF NOT EXISTS idx_orchestration_operator_actions_project_created
    ON generation_orchestration_operator_actions(project_id, created_at);
"""


OPERATIONAL_PERSISTENCE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS operational_evidence_records (
    evidence_key TEXT PRIMARY KEY,
    source_record_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    source_service TEXT NOT NULL,
    artifact_filename TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    project_id INTEGER,
    source_created_at TEXT,
    recorded_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(evidence_type, artifact_sha256)
);

CREATE TABLE IF NOT EXISTS operational_persistence_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    scanned INTEGER NOT NULL DEFAULT 0,
    imported INTEGER NOT NULL DEFAULT 0,
    unchanged INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_operational_evidence_type_recorded
    ON operational_evidence_records(evidence_type, recorded_at);
CREATE INDEX IF NOT EXISTS idx_operational_evidence_project_recorded
    ON operational_evidence_records(project_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_operational_persistence_runs_completed
    ON operational_persistence_runs(completed_at);
"""


MIGRATIONS = (
    (1, INITIAL_SCHEMA_SQL),
    (2, MULTI_SOURCE_SCHEMA_SQL),
    (3, PRODUCT_POLISH_SCHEMA_SQL),
    (4, GENERATION_RETRY_SCHEMA_SQL),
    (5, GENERATION_HISTORY_SCHEMA_SQL),
    (6, GENERATION_PERFORMANCE_SCHEMA_SQL),
    (7, GENERATION_PERFORMANCE_POLICY_SCHEMA_SQL),
    (8, GENERATION_INCIDENT_SCHEMA_SQL),
    (9, GENERATION_INCIDENT_SLA_SCHEMA_SQL),
    (10, GENERATION_INCIDENT_RUNBOOK_SCHEMA_SQL),
    (11, GENERATION_INCIDENT_REVIEW_SCHEMA_SQL),
    (12, GENERATION_PROBLEM_SCHEMA_SQL),
    (13, GENERATION_AUTOMATED_REMEDIATION_SCHEMA_SQL),
    (14, GENERATION_RELIABILITY_SLO_SCHEMA_SQL),
    (15, GENERATION_COST_CAPACITY_SCHEMA_SQL),
    (16, GENERATION_HARDENING_SCHEMA_SQL),
    (17, GENERATION_ORCHESTRATION_SCHEMA_SQL),
    (18, GENERATION_ADAPTIVE_ROUTING_SCHEMA_SQL),
    (19, GENERATION_DYNAMIC_SCHEDULING_SCHEMA_SQL),
    (20, GENERATION_DEADLINE_SCHEDULING_SCHEMA_SQL),
    (21, GENERATION_ORCHESTRATION_UI_SCHEMA_SQL),
    (22, GENERATION_ORCHESTRATION_WORKFLOW_UI_SCHEMA_SQL),
    (23, OPERATIONAL_PERSISTENCE_SCHEMA_SQL),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migration_statements(sql: str) -> list[str]:
    statements: list[str] = []
    pending = ""
    for line in sql.splitlines():
        pending = f"{pending}\n{line}".strip()
        if sqlite3.complete_statement(pending):
            statements.append(pending.rstrip(";").strip())
            pending = ""
    if pending.strip():
        statements.append(pending.strip())
    return statements


def run_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {
        int(row["version"])
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, sql in sorted(MIGRATIONS, key=lambda item: item[0]):
        if version in applied:
            continue
        for statement in migration_statements(sql):
            try:
                connection.execute(statement)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)",
            (version, utc_now()),
        )
