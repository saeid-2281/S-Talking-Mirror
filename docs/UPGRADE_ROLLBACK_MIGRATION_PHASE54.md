# Phase 54 — Upgrade, Rollback and Migration Validation

Phase 54 adds a deterministic recovery boundary between release packaging and automatic update delivery.

## Goals

- validate in-place, portable-to-installed and rollback paths;
- reject databases created by a newer unsupported schema;
- run migrations against a disposable database copy before changing active data;
- create an integrity-checked pre-upgrade backup;
- preserve settings, provider metadata, DPAPI-protected credential files, pronunciation dictionaries and application data;
- never move or delete external source documents, projects or generated audio;
- create a second safety backup before an acknowledged restore;
- provide a command-line recovery path that runs while S Talking is closed.

## UI

Open **Reports → Upgrade & Recovery** or use the command palette action **Reports: Upgrade & Recovery**.

The dialog exposes compatibility gates, schema information, backup evidence, disposable migration validation and a dry-run restore plan. Actual restore is deliberately delegated to `scripts/upgrade-validation.ps1` so the GUI and SQLite handles can be closed first.

## Backup structure

Each backup contains:

- `upgrade-backup-manifest.json` with SHA-256 and size evidence;
- a consistent SQLite backup created through the SQLite backup API;
- settings and provider-profile metadata;
- encrypted credential files without decrypting or displaying their contents;
- pronunciation dictionaries and non-database files under the data directory;
- `RECOVERY.md` and a machine-readable result.

Logs, reports, caches, generated outputs and external project source files are not copied.

## Safe commands

Validate the current installation:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\upgrade-validation.ps1 -ValidateMigration
```

Create and verify a pre-upgrade backup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\upgrade-validation.ps1 -CreateBackup -ValidateMigration
```

Validate a portable-to-installed transition:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\upgrade-validation.ps1 `
  -Mode portable_to_installed `
  -SourceRoot "D:\Portable\S-Talking"
```

Restore only after S Talking is closed and the dry-run plan has been reviewed:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\upgrade-validation.ps1 `
  -RestoreBackup "<verified-backup-path>" `
  -AcknowledgeRestore
```

## Compatibility policy

A source schema lower than schema 22 is migrated only on a disposable copy during validation. A source or backup schema greater than 22 is blocked. Rollback never attempts to reverse SQLite migrations in place; it restores a verified compatible backup instead.

No database migration is introduced by Phase 54. The application schema remains 22.
