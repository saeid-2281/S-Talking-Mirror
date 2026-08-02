# Phase 34 — Batch Generation Planning, Cost Preview & Preflight UX

Phase 34 turns preflight from a validation-only screen into a decision surface.
The current scope is summarized with price, duration, completion time, quota,
queue budget, confidence and an explicit risk assessment.

## Planning scenarios

Every run contains three deterministic scenarios:

- Base: no retry reserve.
- Expected retries: 5% per configured retry, capped at 25%.
- Stress test: a fixed 25% reserve.

The scenarios use the same project/provider/model pricing lookup as cost and
capacity reporting. Historical throughput is used when available; otherwise the
existing fallback estimate is retained. Configured inter-request delay is added
to elapsed-time estimates.

## Safety and compatibility

- Preflight validation and start gating remain unchanged.
- No database migration is required; schema remains version 22.
- Existing `PreflightState` fields and dialog handles are preserved.
- The nested plan is included in JSON, Markdown and HTML reports.
- No credentials or API keys are stored in the plan.
