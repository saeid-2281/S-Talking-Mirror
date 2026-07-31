# Generation Monitor Pro v1.0 — Phase 15

## Cost & Capacity Intelligence

Phase 15 adds a financial and operational planning layer to Generation Monitor.
It records estimated or provider-reported Session cost, measures retry waste,
compares Provider/Model efficiency, evaluates daily/weekly/monthly budgets, and
forecasts the cost and completion time of the current queue before Generation
starts.

## Capabilities

- Global and project-specific cost budget policies.
- Configurable reporting currency.
- Daily, weekly, and monthly spend limits.
- Configurable budget warning percentage.
- Maximum allowed cost for queued work.
- Default price per one million characters.
- Provider-specific and Provider/Model-specific pricing overrides.
- Project-specific pricing overrides with global fallback.
- Pricing source and effective-date metadata.
- Estimated cost for every completed Generation Session.
- Optional provider-reported actual cost from Session monitor metadata.
- Estimated retry characters and retry-waste cost.
- Billable-character calculation with configurable retry billing.
- Automatic backfill of historical Session cost when a rate becomes available.
- Provider/Model comparison for total cost, cost per file, success rate,
  throughput, and retry waste.
- Current queue file and character counts.
- Queue completion forecast using median historical files/minute or
  characters/minute.
- Confidence rating based on available comparable historical Sessions.
- Estimated queue cost and completion timestamp.
- Projected monthly spend based on current month-to-date usage.
- Budget states: Disabled, Healthy, Warning, Critical.
- Deduplicated cost notifications with configurable cooldown.
- Activity Timeline registration for cost and capacity alerts.
- Persisted Cost & Capacity snapshots.
- JSON and CSV exports.
- Cost & Capacity dashboard in Reports and Command Palette.
- Cost estimate in Preflight reports before Generation starts.

## Pricing precedence

The effective price is selected in this order:

1. Project + Provider + Model
2. Project + Provider + wildcard Model
3. Global + Provider + Model
4. Global + Provider + wildcard Model
5. Project or global default price policy

Phase 15 intentionally does not perform currency conversion. Pricing rates,
budgets, and provider-reported actual cost should use the same configured
currency.

## Cost calculation

```text
retry characters = average characters per job × retry events
billable characters = source characters + retry characters
estimated cost = billable characters / 1,000,000 × configured rate
```

Retry characters are included only when `bill_retry_characters` is enabled.
When a provider reports an actual cost in Session monitor metadata, the actual
value is preserved and used as the effective Session cost.

## Capacity forecast

The queue forecast prefers median historical characters per minute for the same
Project, Provider, and Model. If character throughput is unavailable, it uses
median files per minute. With no comparable history, it uses the existing safe
fallback duration of three seconds per queued file.

Confidence levels:

| Comparable Sessions | Confidence |
| --- | --- |
| 0–1 | Low |
| 2–4 | Medium |
| 5 or more | High |

## Database migration

Schema version 15 adds:

- `generation_cost_budget_policies`
- `generation_pricing_rates`
- `generation_session_costs`
- `generation_cost_capacity_snapshots`

Before upgrading an existing database, the migration system creates a
`.pre-v15.bak` backup. Existing Generation History, Performance, Incident,
Problem, Runbook, Review, Automation, and Reliability data remain intact.

## Validation commands

```powershell
.\.venv\Scripts\python.exe -m compileall app tests
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q tests/test_generation_monitor_pro_v100_phase15.py
.\.venv\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File .\scripts\quality-gate.ps1 -Full
```
