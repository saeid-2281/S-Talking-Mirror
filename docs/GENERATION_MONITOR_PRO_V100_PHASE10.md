# Generation Monitor Pro v1.0 — Phase 10

## Incident Runbooks & Remediation Tracking

Phase 10 turns incidents into guided, repeatable recovery workflows. Operators can create reusable runbook templates, receive recommendations based on incident severity and fingerprint, execute a step-by-step remediation checklist, and retain a complete history of every recovery attempt.

## Runbook templates

Runbooks can be global or project-specific. Each template stores:

- name and description
- enabled state
- severity filter
- optional regular-expression match for the incident fingerprint, title, or summary
- ordered remediation steps

The Incident Center seeds safe default runbooks for provider/network failures, output/filesystem failures, and general critical triage when no global runbooks exist. Project-specific matches are ranked above global recommendations.

## Remediation executions

Starting a runbook creates an immutable step snapshot for the selected incident. Only one active execution is allowed per incident. Each step can be marked:

- Pending
- In progress
- Completed
- Skipped
- Failed

Step notes, actor, completion time, and execution progress are persisted. Completing or skipping every step completes the execution automatically. A failed step marks the execution failed; failed or cancelled executions can be resumed safely.

## Incident Center integration

The Incident Center adds a Runbook action for one selected incident. The runbook window supports:

- ranked recommendations
- global and project templates
- creating, editing, enabling, disabling, and deleting templates
- starting a recommended runbook
- viewing execution history
- updating individual step status
- resuming or cancelling an execution
- live completion percentage

Incident details now include recent runbook executions. Runbook start, step changes, completion, failure, cancellation, and resume actions are recorded in both the incident update history and Activity Timeline.

## Export

Generation incident JSON and CSV exports now include the full remediation history. Each execution contains its runbook snapshot, progress, actor, timestamps, step statuses, notes, and completion data.

## Database

Migration version 10 creates:

- `generation_incident_runbooks`
- `generation_incident_remediations`

Existing project and incident records are preserved. Before upgrading an older project database, the database layer creates a `.pre-v10.bak` backup automatically.
