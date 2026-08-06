# Phase 72 — Capacity Forecast, Saturation Guard & Degradation Readiness

Phase 72 adds a privacy-safe and human-controlled capacity governance workflow.
It consumes aggregate capacity observations plus intact Phase 71 SLO evidence,
then calculates current headroom, forecast headroom, saturation timing, queue
pressure, worker utilization, memory utilization and provider throttling.

## Safety contract

The workflow never performs any of the following automatically:

- infrastructure scaling;
- load shedding;
- queue configuration changes;
- deployment or rollback;
- application restart;
- release approval or publication.

Every observation and decision is human reviewed, stored locally and protected by
SHA-256. Audit packs include a signed manifest and an independent receipt.

## Release gates

- `allow`: capacity and inherited SLO evidence support release consideration.
- `manual_review`: warnings require a scale or degraded-mode decision.
- `hold`: saturation, severe pressure, invalid custody or inherited SLO blockers
  prevent release approval.

## Interfaces

- GUI: **Reports → Capacity Forecast & Degradation Readiness**
- CLI: `--capacity-snapshot`, `--create-capacity-observation`,
  `--create-capacity-decision` and verification flags.
- PowerShell: `scripts/capacity-readiness.ps1`
