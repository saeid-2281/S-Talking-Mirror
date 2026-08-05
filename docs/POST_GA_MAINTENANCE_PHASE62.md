# Phase 62 — Post-GA Reliability & Maintenance Operations

Phase 62 adds a non-destructive operational baseline for S-Talking after the stable `1.0.0` general-availability promotion.

## Goals

- Verify the tamper-evident stable promotion receipt and all artifacts referenced by it.
- Verify the stable update feed, sidecar digest and downloadable package hashes.
- Verify that the stable rollback point is still intact before maintenance work.
- Detect stale release evidence, incomplete rollout, low disk reserve and read-only runtime paths.
- Reject maintenance evidence that contains credential-like fields, token-like values or absolute local paths.
- Write a privacy-safe and tamper-evident post-GA maintenance baseline.
- Prepare a five-step manual maintenance plan without deleting, publishing, updating or restarting anything.

## User interface

Open **Reports → Post-GA Maintenance**. The workspace shows every gate, evidence detail and remediation. Writing a baseline or plan requires explicit acknowledgement.

## PowerShell workflow

Preflight only:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\post-ga-maintenance.ps1
```

Write the verified baseline and manual maintenance plan:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\post-ga-maintenance.ps1 `
  -RunQualityGate `
  -PreparePlan `
  -AcknowledgeMaintenance
```

## Frozen CLI contracts

- `--post-ga-maintenance-snapshot`
- `--write-post-ga-baseline`
- `--verify-post-ga-baseline <path>`
- `--prepare-post-ga-maintenance-plan`
- `--verify-post-ga-maintenance-plan <path>`
- `--acknowledge-post-ga-maintenance`

## Safety contract

Phase 62 never performs automatic cleanup, artifact deletion, update-feed publication, application update, restart, Git commit, Git tag or Git push. Every operational change remains a separate human-controlled action.
