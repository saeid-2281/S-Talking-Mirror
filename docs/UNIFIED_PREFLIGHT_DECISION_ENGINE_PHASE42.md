# Unified Preflight Decision Engine — Phase 42

Phase 42 introduces one deterministic and explainable launch decision shared by the final launch review, persisted launch receipts, audit exports, and automated tests.

## Decision contract

Every evaluated launch ends in exactly one status:

- `ready`: all evaluated sources are ready.
- `ready_with_warnings`: generation may start, but non-blocking warnings remain.
- `approval_required`: generation may start only after the required acknowledgement or exception review.
- `blocked`: at least one blocking source must be resolved before generation.

Each result contains a stable SHA-256 decision trace, normalized signals, prioritized recommendations, and blocker, warning, and approval counts.

## Integrated decision sources

The engine normalizes inputs from:

- Text and source preparation issues
- Preflight validation
- Provider, model, and voice readiness
- Output directory and existing-file policy
- Batch planning and retry exposure
- Quota and pricing availability
- Project baseline drift guard
- Time-bound exception approvals

## UI integration

The Generation Launch Review now includes a Unified Preflight Decision section with:

- Final decision status
- Decision trace ID
- Decision summary
- Prioritized next actions

The existing acknowledgement checklist and launch controls remain unchanged.

## Receipt integration

Launch receipts persist the unified decision inside the existing integrity-protected JSON payload. Receipt loading, searching, detail display, and exports include the decision status, summary, and trace ID. API keys, credentials, and source text are never serialized.

## Compatibility

- Database schema remains version 22.
- Launch receipt schema remains version 2.
- Legacy receipts without unified decision metadata remain readable.
- Existing public UI handles, theme tokens, and button labels are preserved.
