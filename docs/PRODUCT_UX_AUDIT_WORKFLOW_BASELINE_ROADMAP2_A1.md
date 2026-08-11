# Roadmap 2 / Track A / Phase A1 — Full Product UX Audit & Workflow Baseline

## Purpose

Phase A1 starts the S-Talking 1.x Product Experience roadmap after the Phase 98–112 provider platform reached GA certification. The provider architecture is treated as a stable platform boundary. A1 does not redesign provider selection, Preflight, Generation, recovery, or Plugin SDK behavior.

The phase creates a deterministic product-experience baseline before A2–A10 change user-facing workflows.

## Audited journeys

1. First run & orientation
2. Provider setup & account readiness
3. Voice & model discovery
4. Text/source preparation
5. Queue planning & batch operations
6. Preflight & generation approval
7. Live generation & progress
8. Failure recovery & resume
9. Audio review & export
10. Settings, help & accessibility

Each journey is scored from reviewed source evidence. Required evidence identifies structural continuity; optional evidence identifies product-experience opportunities. Missing optional evidence becomes backlog input, not an automatic code change.

## Safety boundary

Assessment is read-only. It performs no network calls, provider probes, catalog refreshes, database writes, provider/account/voice/model changes, generation start/restart, or cross-provider failover. Snapshot export happens only when the user explicitly clicks Export baseline snapshot.

The Phase 112 GA boundary remains authoritative:

- Database schema remains 23.
- Smart Routing remains recommendation-only.
- Provider recovery remains explicit and user-controlled.
- Plugin SDK activation remains explicit and session-only.
- Preflight validates; the user decides; Generation Engine executes.
- No hidden cross-provider failover.

## Output

`reports/product-ux-audit/` contains explicit exported snapshots. Each snapshot contains the 10 journeys, evidence, score, prioritized backlog, source commit and a SHA-256 payload digest.

## Roadmap transition

A1 establishes evidence only. The next phase is **A2 — First-run / Onboarding Experience**, which should consume A1 backlog evidence rather than introducing another architecture layer.
