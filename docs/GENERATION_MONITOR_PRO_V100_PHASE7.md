# Generation Monitor Pro v1.0 — Phase 7

## Performance Budgets & Alert Management

Phase 7 makes the regression engine configurable and turns alerts into a managed lifecycle instead of one-off notifications.

## Performance budgets

Global defaults or project-specific budgets can configure:

- minimum comparable sessions
- rolling baseline window
- throughput warning and critical drops
- seconds-per-job warning and critical increases
- completion-rate warning and critical drops
- failure-rate warning and critical increases
- retry-rate warning and critical increases
- duplicate-alert cooldown
- alert enable/disable state

Project budgets override global defaults. Existing history can be recalculated immediately after a budget change.

## Alert lifecycle

Every warning or critical session stores:

- stable regression fingerprint
- alert state: open, acknowledged, suppressed, silenced, or none
- Notification Center identifier
- alert creation time
- acknowledgement time

Equivalent alerts inside the configured cooldown are suppressed. Alerts can be silenced temporarily per project or globally and resumed manually. Open alerts can be acknowledged from Generation History.

## Product integration

Generation History now includes:

- Alert column and alert-state filter
- open-alert count in the summary
- alert fingerprint and lifecycle timestamps in details
- acknowledge selected alerts
- silence alerts for one hour
- resume alerts
- performance-budget editor
- alert metadata in JSON and CSV exports

Suppressed and silenced alerts are recorded in Activity Timeline without creating duplicate Notification Center entries.

## Database

Migration version 7 creates `generation_performance_budgets` and adds alert lifecycle fields and indexes to `batch_sessions`. Existing migration backup behavior remains active.
