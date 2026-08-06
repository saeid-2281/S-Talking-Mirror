# Phase 69 — Reliability Assurance Renewal & Exception Follow-up

Phase 69 consumes verified Phase 68 assurance attestation, audit-pack and receipt triplets. It validates source custody, evaluates lifecycle age, surfaces due, overdue, withheld and carried exceptions, and creates a local tamper-evident renewal record after explicit human acknowledgement.

## Safety contract

The workflow never edits Phase 68 evidence and never automatically accepts risk, creates or updates a ticket, schedules work, uploads, publishes, patches, deploys, rolls back or restarts the application. All renewal and follow-up artifacts remain local until a human explicitly moves them.

Text fields reject obvious credentials and local absolute Windows paths. Records contain identifiers, lifecycle status, categorical metrics, approved summaries and SHA-256 evidence only.

## Source custody

Each renewal source consists of exactly one verified Phase 68 assurance attestation, its matching audit pack and matching receipt. Invalid, duplicated, unpaired or tampered source items block renewal.

## Lifecycle policy

A human selects:

- assurance validity between 7 and 3650 days
- a due-soon window between 1 and 365 days, never longer than validity

An explicit Phase 68 `next_review_date` takes precedence when it is earlier than the policy validity date.

Lifecycle states are:

- `current`
- `due_soon`
- `overdue`
- `withheld`

## Follow-up exceptions

The workflow creates governed follow-up items for:

- assurance due soon
- assurance overdue
- withheld assurance
- `assure_with_exceptions`
- open exceptions recorded in the Phase 68 source metrics

## Human renewal decisions

- `renew` — allowed only with zero follow-up items
- `renew_with_follow_up` — requires a privacy-safe human owner and a next review date 1–365 days in the future
- `withhold_renewal` — records that lifecycle or source exceptions prevent renewal and still requires a follow-up owner and review date

Every decision requires explicit acknowledgement and a privacy-safe renewal statement.

## Renewal audit pack

The generated ZIP contains:

- renewal record
- exception follow-up register
- renewal snapshot
- verified Phase 68 source triplets
- signed manifest

A separate receipt records ZIP size and SHA-256. Verification detects changes to the renewal record, follow-up register, manifest, source artifacts, ZIP or receipt.

## Graphical workflow

Open **Reports → Assurance Renewal & Follow-up**. Select Phase 68 triplets, inspect lifecycle gates and follow-up items, enter the human renewal decision and create the local audit pack.

## Command line

Use `scripts/reliability-assurance-renewal.ps1` to export a snapshot, create a renewal audit pack or verify renewal artifacts.

## Stored artifacts

```text
artifacts/reliability-assurance-renewal/
    snapshots/
    renewals/
    follow-up/
    audit-packs/
    receipts/
    latest-reliability-renewal.json
    latest-reliability-renewal-receipt.json
```
