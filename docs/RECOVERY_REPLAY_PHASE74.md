# Phase 74 — Recovery Replay Integrity, Duplicate Prevention & Billing Safety

Phase 74 extends the verified controlled-degradation evidence from Phase 73 into a product-specific recovery replay workflow. It records whether queued generation work can be resumed without duplicate provider requests, duplicate audio outputs, orphan artifacts, manifest drift or unexpected billing variance.

## Safety boundary

The workflow is evidence-only and human controlled. It **never resumes queues**, retries jobs, changes provider routing, deletes artifacts, regenerates audio, performs billing actions, deploys, rolls back, restarts, publishes or makes a release decision automatically.

## Workflow

1. Select an intact Phase 73 result, attestation, audit pack and receipt set.
2. Create and acknowledge a reviewed replay plan.
3. Review the readiness gates.
4. Conduct the replay manually in an isolated or approved environment.
5. Record observed job, duplicate, artifact, manifest, cost and recovery measurements.
6. Preserve successful evidence as `verified` or failed evidence as `withheld`.
7. Verify the generated result, attestation, audit pack and receipt before use.

## Replay checks

- The attempted job count matches the reviewed expected count.
- Resumed and completed job counts are internally consistent.
- Duplicate API requests and duplicate outputs stay within reviewed limits.
- Orphan artifacts and manifest mismatches stay within reviewed limits.
- Cost variance stays within the reviewed percentage.
- Recovery completes within the reviewed target.
- Execution receipt continuity and output checksums are verified.
- Dedicated recovery regression tests pass.

## Interfaces

- GUI: **Reports → Recovery Replay Integrity & Duplicate Prevention**
- CLI: `python -m app.frozen_main --recovery-replay-snapshot`
- PowerShell: `scripts/recovery-replay.ps1`

All generated JSON and ZIP artifacts are tamper-evident through SHA-256 digests and safe archive-path validation.
