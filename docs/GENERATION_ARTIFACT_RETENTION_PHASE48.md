# Phase 48 — Receipt, Approval & Run Retention

Phase 48 adds a dedicated, auditable retention workflow for generation governance artifacts.
It complements database retention in Hardening & Maintenance without changing database schema 22.

## Safety boundary

The retention service only considers known files below the reports directory:

- launch receipt JSON/Markdown pairs;
- execution session, execution receipt and output-manifest metadata;
- safe-resume receipts;
- terminal guard approval records;
- terminal budget approval and reservation records;
- orphaned known companion files after a grace period.

Audio outputs, project source files, settings, credentials and database files are never candidates.
Active execution sessions and active approvals/reservations are also excluded. Current project baselines, launch receipts linked to active runs, and parent runs referenced by active recovery receipts are protected as Review-only.

## Workflow

1. Configure project-scoped retention windows.
2. Generate a deterministic dry-run preview.
3. Review Archive, Delete and Review-only candidates.
4. Export the preview when external review is required.
5. Create a ZIP archive and JSON manifest before cleanup.
6. Verify archive SHA-256 and ZIP integrity.
7. Remove only the exact artifacts represented by the unchanged preview.
8. Record the retention run, archive path, checksum and reclaimed bytes.

A stale preview cannot be applied. Integrity mismatches are Review-only by default and require an
explicit policy change before they can be removed.

## UI

`Reports → Artifact Retention` provides:

- project-scoped policy controls;
- cleanup summary and candidate table;
- retention run history;
- dry-run recording;
- JSON/CSV preview export;
- archive folder access;
- explicit confirmation before applied cleanup.

## Persistence

Retention policy and audit records are stored under:

```text
reports/artifact-retention/generation-artifact-retention-policies.json
reports/artifact-retention/generation-artifact-retention-runs.json
```

Archives and their manifests are stored under:

```text
reports/artifact-retention-archives/
```
