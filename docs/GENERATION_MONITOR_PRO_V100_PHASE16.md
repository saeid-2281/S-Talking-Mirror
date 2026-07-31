# Generation Monitor Pro v1.0 — Phase 16

## v1.0 Hardening & Release

Phase 16 freezes the Generation Monitor feature set and adds operational safeguards for the final v1.0 release.

## Database release gate

The hardening service validates:

- Applied schema migrations against the application-supported schema version.
- SQLite `quick_check` or full `integrity_check`.
- Foreign-key integrity.
- Core operational table counts.
- Database size and maintenance history.

The application release metadata now reports database schema version 16. Release Readiness treats incomplete migrations, integrity failures, and foreign-key violations as failed checks.

## Migration safety

Pre-migration backups now use the SQLite online backup API rather than copying the database file directly. This produces a consistent backup when SQLite uses WAL mode or has pending pages.

Before migration 16, the application creates:

```text
s_talking.db.pre-v16.bak
```

The backup is validated with `PRAGMA quick_check` before it replaces any existing artifact.

## Verified backup and restore

Manual backups include:

- A transactionally consistent SQLite database file.
- SHA-256 checksum.
- Schema version.
- File size and creation time.
- JSON manifest.
- Maintenance audit record.

Restore performs these steps:

1. Validate the selected backup.
2. Reject backups newer than the running application.
3. Create a verified pre-restore backup.
4. Restore through SQLite's backup API into a temporary file.
5. Apply any pending migrations.
6. Run full integrity and foreign-key validation.
7. Roll back to the pre-restore backup if validation fails.

The active database cannot be selected as its own restore source.

## Retention policy

Global or project-scoped policies control retention for:

- Completed Generation sessions without incident links.
- Read notifications.
- Activity Timeline events.
- Reliability snapshots.
- Cost and capacity snapshots.
- Maintenance audit runs.
- Number of verified database backups.

Cleanup always supports a preview before deletion. Sessions referenced by an Incident are preserved even when their local `incident_id` field is missing or stale.

Project-scoped cleanup does not delete global notifications. Read-notification cleanup is only performed by the global policy.

## Startup validation

When enabled, startup runs a database quick check and stores the result in the maintenance audit history. The setting is controlled by the global maintenance policy.

## UI

`Reports > Hardening & Maintenance` provides:

- Quick and full integrity checks.
- Verified backup creation.
- Safe restore with confirmation.
- Retention-policy editing.
- Cleanup preview and apply actions.
- Backup inventory with checksum and schema.
- Maintenance audit history.
- JSON and CSV release-hardening reports.

The same screen is available from the Command Palette.

## Migration 16 tables

- `generation_maintenance_policies`
- `generation_maintenance_runs`

## Release validation

Recommended final gate:

```powershell
.\.venv\Scripts\python.exe -m compileall app tests
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q tests/test_generation_monitor_pro_v100_phase16.py
.\.venv\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File .\scripts\quality-gate.ps1 -Full
```

A successful Phase 16 gate marks `Generation Monitor Pro v1.0` as feature-complete and release-hardened.
