# Phase 67 — Preventive Action Effectiveness & Residual Risk

Phase 67 completes the prevention-governance loop introduced by Phase 66. It verifies the immutable incident-prevention baseline and action register, records separate human action attestations, evaluates verified post-baseline recurrence and creates local tamper-evident effectiveness and decision records.

## Safety contract

The workflow is human controlled. It never edits the Phase 66 baseline or register and never automatically completes an action, accepts risk, creates a ticket, schedules work, patches, deploys, rolls back, restarts or publishes a record.

All action attestations and review decisions require explicit acknowledgement. Text fields reject obvious credentials and local absolute Windows paths. Records include only identifiers, categorical outcomes, hashes and privacy-safe summaries.

## Action attestations

Each attestation references one action from the verified Phase 66 register and records one of these outcomes:

- `completed`
- `deferred`
- `risk_accepted`

Completed actions require a privacy-safe evidence reference. Attestations are immutable JSON records with SHA-256 integrity and retain `automatic=false` controls for every operational side effect.

## Effectiveness analysis

The review compares Phase 66 recurrence patterns with verified Phase 65 closure certificates created after the prevention baseline. Patterns are classified as:

- `monitoring` — no new recurrence, but observation or action completion is incomplete
- `effective` — at least 30 days of observation, no new recurrence and all relevant actions resolved
- `ineffective` — one or more verified post-baseline recurrences

Residual risk is recalculated without changing the original Phase 66 risk score.

## Human decisions

The review supports four local decisions:

- `continue_monitoring`
- `escalate_prevention`
- `accept_residual_risk`
- `close_effective`

Effective closure requires at least 30 days of observation, no recurrence, no ineffective pattern and no open, deferred, overdue or risk-accepted action. Residual-risk acceptance requires a separate human risk attestation and is blocked for residual scores at or above 90.

## Graphical workflow

Open **Reports → Prevention Effectiveness & Risk**. Select the verified Phase 66 baseline and matching action register, review post-baseline closures, record action outcomes, inspect gates and create an acknowledged review decision.

## Command line

Use `scripts/prevention-effectiveness.ps1` to export snapshots, record action attestations, create review decisions and verify attestation, review or decision integrity.

## Stored artifacts

Artifacts are written below:

```text
artifacts/prevention-effectiveness/
    attestations/
    reviews/
    decisions/
    latest-action-attestation.json
    latest-effectiveness-review.json
    latest-effectiveness-decision.json
```

These artifacts remain local until a human explicitly moves or publishes them.
