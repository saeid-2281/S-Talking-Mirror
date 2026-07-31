# Generation Monitor Pro v1.0 — Phase 13

## Safe Automated Remediation

Phase 13 adds a guarded automation layer on top of Incident Management, Known
Problems, and Incident Runbooks. The implementation is deliberately fail-safe:
automation is disabled by default, defaults to dry-run mode, and supports only
internal allowlisted actions. It does not execute arbitrary shell commands,
scripts, or user-supplied code.

## Capabilities

- Global and project-specific remediation automation policies.
- Dry-run planning without changing queue or incident state.
- Internal action allowlist and validation at policy and runbook boundaries.
- Manual confirmation before live mutating actions.
- Optional unattended mutating actions when explicitly enabled by policy.
- Per-incident automatic-run limits and cooldown enforcement.
- Prevention of concurrent automated remediation for the same incident.
- Trigger support for incident creation and known-problem recurrence.
- Action-level audit results with status, message, timestamps, and details.
- Rollback instructions and explicit rollback audit state.
- Notification, Activity Timeline, and Incident update integration.
- JSON and CSV incident exports containing automated-remediation history.
- Runbook editor support for safe automation action definitions.
- Policy and execution controls in the Incident Runbook dialog.

## Supported internal actions

| Action | Type | Purpose |
| --- | --- | --- |
| `record_workaround` | Safe | Records the known workaround in the incident history. |
| `evaluate_sla` | Safe | Re-evaluates SLA and escalation state. |
| `acknowledge_incident` | Mutating | Acknowledges the incident. |
| `retry_transient_jobs` | Mutating | Retries only failed jobs classified as transient. |
| `reset_interrupted_jobs` | Mutating | Resets interrupted running jobs to a recoverable state. |

Unknown action types are rejected. There is no shell-command or arbitrary-code
action type.

## Safety model

1. Automation policy is disabled by default.
2. Dry run is the default execution mode.
3. Runbook actions must be included in the policy allowlist.
4. Manual live mutating actions require explicit confirmation.
5. Automatic live mutating actions require an explicit unattended-mutation
   policy setting; otherwise they are forced to dry run.
6. Maximum automatic runs and cooldown are enforced per incident and runbook.
7. A second execution cannot start while another automated remediation is
   running for the same incident.
8. Every blocked, planned, completed, failed, or rollback-marked execution is
   persisted for audit.

## Database migration

Schema version 13 adds:

- `generation_remediation_automation_policies`
- `generation_automated_remediations`
- Automation configuration columns on `generation_incident_runbooks`

Before upgrading an existing database, the migration system creates a
`.pre-v13.bak` backup. Existing Incident, Review, Corrective Action, Known
Problem, and Runbook data remain intact.

## Validation commands

```powershell
.\.venv\Scripts\python.exe -m compileall app tests
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q tests/test_generation_monitor_pro_v100_phase13.py
.\.venv\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File .\scripts\quality-gate.ps1 -Full
```
