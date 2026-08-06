# Phase 68 — Reliability Assurance, Exception Governance & Audit Pack

Phase 68 consolidates verified Phase 67 effectiveness reviews and their human decisions into a local reliability-assurance cycle. It verifies one-to-one source custody, converts non-final outcomes into governed exceptions and creates a privacy-safe tamper-evident audit pack after explicit human acknowledgement.

## Safety contract

The workflow never edits Phase 67 evidence and never automatically accepts risk, creates or updates a ticket, schedules work, uploads, publishes, patches, deploys, rolls back or restarts the application. Audit packs remain local until a human explicitly moves them.

Text fields reject obvious credentials and local absolute Windows paths. Records contain identifiers, categorical metrics, approved summaries and SHA-256 evidence only.

## Source custody

Each assurance source consists of exactly one verified Phase 67 effectiveness review and its matching human decision. Invalid, duplicated, unpaired or tampered sources block assurance. Records outside the selected review window are ignored rather than changed.

## Exception governance

These Phase 67 outcomes create open exceptions:

- `continue_monitoring`
- `escalate_prevention`
- `accept_residual_risk`
- overdue preventive actions
- verified recurrence or ineffective prevention

A `close_effective` source with no conflicting metrics creates no exception.

## Human assurance decisions

- `assure` — allowed only with zero open exceptions
- `assure_with_exceptions` — requires a human exception owner and a next review date 1–365 days in the future
- `withhold_assurance` — records that open exceptions prevent assurance

Every decision requires an explicit acknowledgement and a privacy-safe assurance statement.

## Audit pack

The generated ZIP contains the assurance attestation, snapshot, verified Phase 67 source copies and a signed manifest. A separate receipt records ZIP size and SHA-256. Verification detects changes to the attestation, manifest, source files, ZIP or receipt.

## Graphical workflow

Open **Reports → Reliability Assurance & Audit Pack**. Select Phase 67 reviews and decisions, inspect gates and exceptions, enter the human assurance decision and create the local audit pack.

## Command line

Use `scripts/reliability-assurance.ps1` to export a snapshot, create an assurance audit pack or verify an attestation/pack.

## Stored artifacts

```text
artifacts/reliability-assurance/
    snapshots/
    attestations/
    audit-packs/
    receipts/
    latest-reliability-assurance.json
    latest-reliability-assurance-receipt.json
```
