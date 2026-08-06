# Phase 73 — Controlled Degradation Drill & Recovery Validation

Phase 73 converts the Phase 72 capacity forecast into reviewed, tamper-evident
degradation drill evidence.

## Workflow

1. Select matching Phase 72 capacity snapshot, decision, audit pack and receipt.
2. Create one or more human-reviewed plans for required degradation scenarios.
3. Review readiness gates and scenario coverage.
4. Run the drill manually in an isolated or staging environment.
5. Record observed reduction, queue, recovery, error and data-loss measurements.
6. Preserve the result, attestation, audit pack and receipt locally.

## Safety boundary

The workflow never performs load shedding, queue pauses, provider failover,
worker scaling, restart, deployment, rollback, publication or release approval.
Every operational action remains a separate human decision outside this service.

## Evidence

Artifacts are stored under `artifacts/degradation-readiness/` and use SHA-256
custody checks. Audit packs include a signed manifest and a separate receipt.
Private credentials and local Windows paths are rejected from human text fields.
