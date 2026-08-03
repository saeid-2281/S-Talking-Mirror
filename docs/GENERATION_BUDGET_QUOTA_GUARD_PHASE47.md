# Generation Budget & Quota Guard — Phase 47

Phase 47 converts the existing Cost & Capacity reporting foundation into an active launch guard.

## Decisions

Every planned launch receives one of these budget outcomes:

- `ready`
- `warning`
- `budget_blocked`
- `approved_exception`
- `quota_blocked`
- `disabled`

Provider quota shortfall cannot be bypassed by a budget exception. Cost-limit exceptions are exact, time-bound, usage-limited, and bound to the current decision fingerprint.

## Reservations

A successful launch review creates a reservation before the generation thread starts. The reservation protects both estimated cost and provider characters from concurrent double allocation. It is:

- released when generation does not start;
- settled with actual/derived execution cost when an execution receipt is produced;
- expired automatically when abandoned.

## Audit and receipts

Launch receipts include the complete secret-free budget decision, approval ID, reservation ID, projected daily/weekly/monthly spend, and quota calculation. Existing SHA-256 receipt integrity covers this metadata.

The Reports menu exposes **Budget & Quota Guard** for reservations, approvals, and secret-free JSON/CSV export.

## Persistence

No database migration is required. Guard reservations and approvals are stored in:

```text
reports/generation-budget-guard.json
```

Database schema remains version 22.
