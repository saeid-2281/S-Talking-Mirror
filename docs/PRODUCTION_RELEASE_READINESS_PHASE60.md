# Phase 60 — Production Release Readiness & 1.0 Certification

Phase 60 is the final promotion guard for S Talking. It combines previously generated quality, accessibility, security, performance, crash-recovery, release, update-channel and upgrade-backup evidence into one tamper-evident production attestation.

## Safety boundary

Certification does not publish a release. It does not edit `app/release.py`, create a Git tag, upload artifacts, install an update, change the stable feed or restart the application. The only optional follow-up is a human-readable promotion plan. Writing that plan requires explicit acknowledgement and still requires a separate reviewed version commit, rebuild, signature verification and manual stable-channel publication.

## Required evidence

The certification gate expects these structured artifacts:

- `artifacts/release-check/latest/result.json`
- `reports/ux-accessibility-certification/latest.json`
- `artifacts/security-supply-chain/latest-security-snapshot.json`
- `artifacts/performance-stability/latest-snapshot.json`
- `artifacts/crash-recovery/latest-production-snapshot.json`
- `artifacts/final-release/latest/final-release-manifest.json`
- `artifacts/update-channel/preview/latest.json`
- `artifacts/upgrade-recovery/latest/upgrade-backup-manifest.json`

Missing, invalid, stale or secret-bearing evidence blocks promotion. Preview or beta update-channel evidence is accepted as a warning because the actual move to stable must remain a separate human action.

## Full certification

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\production-certification.ps1 `
  -TargetVersion 1.0.0 `
  -ExpectedTests 849
```

The script first runs the complete release check, refreshes privacy-safe runtime evidence and then writes the production attestation.

## Certification without rerunning the release check

Use this only when `artifacts/release-check/latest/result.json` was generated from the exact current commit:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\production-certification.ps1 `
  -SkipReleaseCheck `
  -TargetVersion 1.0.0 `
  -ExpectedTests 849
```

## Verify an attestation

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\production-certification.ps1 `
  -VerifyAttestation .\artifacts\production-certification\production-release-attestation.json
```

## Prepare a promotion plan

A dry run is produced unless acknowledgement is explicit:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\production-certification.ps1 `
  -SkipReleaseCheck `
  -PreparePromotionPlan
```

To write the plan:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\production-certification.ps1 `
  -SkipReleaseCheck `
  -PreparePromotionPlan `
  -AcknowledgePromotionPlan
```

The plan never performs automatic publishing, tagging or version changes.

## Output

```text
artifacts\production-certification\
  production-release-attestation.json
  production-certification-summary.json
  production-promotion-plan.json
  attestations\production-release-attestation-<timestamp>.json
  promotion-plans\production-promotion-plan-<timestamp>.json
```

The attestation stores only structured statuses, counts, artifact file names, sizes and SHA-256 digests. Absolute local evidence paths, credentials, provider payloads, project text, database rows and generated audio are excluded.
