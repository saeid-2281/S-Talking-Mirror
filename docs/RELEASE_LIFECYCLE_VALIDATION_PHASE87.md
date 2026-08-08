# Phase 87 — Installer / Update / Recovery End-to-End

Phase 87 closes the release-delivery lifecycle without automating production mutations.

## Scope

The new **Release Lifecycle E2E Validation** workspace binds these existing capabilities into one validation chain:

1. Final release manifest verification.
2. Stable update-feed verification.
3. Update-client compatibility against an explicitly selected stable channel without changing user preferences.
4. Manual installer / portable-package handoff readiness.
5. Verified pre-upgrade backup evidence.
6. Upgrade / rollback preflight.
7. Disposable SQLite migration validation.
8. Rollback / recovery compatibility.
9. Stable-promotion provenance and manual-execution contract.

## Safety contract

Validation never performs an automatic download, install, restart, restore, rollback, publish or source-data mutation. Existing services may write diagnostic evidence such as update-check or disposable-migration results.

## Evidence

Snapshots are written under `artifacts/release-lifecycle-validation/`. They contain only artifact-relative source paths and SHA-256 values. Verification re-checks snapshot integrity and source custody.

## CLI

Use `scripts/release-lifecycle-validation.ps1` for a dry validation and `-Export` to write and verify a portable lifecycle snapshot.
