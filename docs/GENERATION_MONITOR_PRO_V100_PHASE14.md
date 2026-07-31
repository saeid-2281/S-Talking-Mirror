# Generation Monitor Pro v1.0 — Phase 14

## Reliability Dashboard & SLO

Phase 14 converts Generation history, Incident Management, Runbooks, and
Corrective Actions into a unified reliability view. It introduces configurable
service-level objectives, rolling error budgets, burn-rate alerts, operational
response metrics, provider reliability comparisons, and persisted reliability
snapshots.

## Capabilities

- Global and project-specific SLO policies.
- Configurable rolling evaluation window and minimum session sample.
- Job-success target and maximum retry-rate objective.
- MTTA and MTTR objectives based on Incident lifecycle timestamps.
- Incident recurrence objective.
- Runbook success-rate objective across manual and live automated remediation.
- Corrective-action completion objective.
- Error-budget calculation from the configured job-success target.
- Warning and critical burn-rate thresholds.
- Reliability states: Disabled, Insufficient Data, Healthy, Warning, Critical.
- Current-versus-previous-window trend: Improving, Stable, Degrading, Unknown.
- Provider-level success, failure, retry, throughput, and health metrics.
- Persisted reliability snapshots with historical comparison.
- Deduplicated Reliability notifications with configurable cooldown.
- Activity Timeline registration for emitted SLO alerts.
- JSON and CSV reliability exports.
- Dashboard drill-down to Generation History and Incident Center.
- Reports menu and Command Palette integration.

## Error budget

The allowed failed-job budget is derived from the target job-success rate:

```text
allowed failures = total jobs × (100 − target success %) / 100
burn rate = observed failure rate / allowed failure rate
```

A burn rate of `1.0x` means the window is consuming the error budget at the
maximum sustainable rate. The default warning threshold is `1.0x`; the default
critical threshold is `2.0x`.

## Default SLO policy

| Objective | Default |
| --- | ---: |
| Rolling window | 30 days |
| Minimum sessions | 3 |
| Job success | 99% or higher |
| Retry rate | 5% or lower |
| MTTA | 60 minutes or lower |
| MTTR | 480 minutes or lower |
| Incident recurrence | 20% or lower |
| Runbook success | 80% or higher |
| Corrective-action completion | 90% or higher |
| Warning burn rate | 1.0x |
| Critical burn rate | 2.0x |
| Alert cooldown | 240 minutes |

## Database migration

Schema version 14 adds:

- `generation_reliability_slo_policies`
- `generation_reliability_snapshots`

Before upgrading an existing database, the migration system creates a
`.pre-v14.bak` backup. Existing Session, Incident, Review, Corrective Action,
Known Problem, Runbook, and Automated Remediation data remain intact.

## Validation commands

```powershell
.\.venv\Scripts\python.exe -m compileall app tests
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q tests/test_generation_monitor_pro_v100_phase14.py
.\.venv\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File .\scripts\quality-gate.ps1 -Full
```
