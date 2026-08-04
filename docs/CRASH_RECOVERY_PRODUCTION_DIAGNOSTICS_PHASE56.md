# Phase 56 — Crash Recovery & Production Diagnostics

Phase 56 adds structured, privacy-safe crash evidence, safe-mode startup and a verified support-bundle workflow. It does not replace the existing generation recovery, session restore, upgrade recovery or database backup workflows; it surfaces their readiness without mutating them.

## Runtime lifecycle

At production startup, `CrashRecoveryService` writes an atomic active-session marker and installs handlers for:

- unhandled Python exceptions;
- unhandled worker-thread exceptions;
- critical and fatal Qt messages.

A normal `MainWindow.closeEvent()` records a clean shutdown and removes the active marker. If the process terminates before this happens, the next production startup reports an unclean previous session. No modal dialog is forced during startup; the status bar points the operator to **Reports → Crash Recovery & Diagnostics**.

## Safe mode

Start with:

```powershell
S-Talking.exe --safe-mode
```

or from source:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\crash-diagnostics.ps1 -LaunchSafeMode
```

Safe mode intentionally skips:

- automatic project/session restore;
- the generation recovery prompt;
- startup update checks.

Database startup recovery still runs so interrupted queue records and stale temporary files remain protected by the existing recovery contract.

## Structured crash reports

Reports are written under:

```text
<artifacts>\crash-recovery\reports\
```

Each report contains:

- exception type and a redacted summary;
- frame file, line and function metadata;
- app/Python/platform metadata;
- opaque session identity;
- a deterministic crash fingerprint;
- acknowledgement state;
- an integrity SHA-256.

Reports never include source-code lines, frame local variables, project text, generated audio, database content, settings content, API profiles or credential values.

## Recovery gates

The UI evaluates:

- previous clean/unclean shutdown state;
- crash-report integrity;
- generation recovery JSON readability;
- session restore JSON readability;
- SQLite `PRAGMA quick_check`;
- safe-mode state.

Integrity and database failures are blockers. Unclean shutdown and malformed resumable state are warnings.

## Verified support bundles

Use the UI action **Export diagnostics bundle** or:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\crash-diagnostics.ps1 -Export
```

Bundles contain only:

- redacted structured crash reports;
- a crash-recovery snapshot;
- file metadata and hashes for recovery evidence;
- a small allowlisted runtime environment summary;
- recent sanitized `.log` files;
- a manifest with size and SHA-256 for every included file.

Bundles explicitly exclude:

- `settings.json`;
- `api-profiles.json`;
- workspace profiles;
- credentials;
- SQLite databases;
- project source files;
- generated audio and output folders;
- provider caches.

Verify a bundle with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\crash-diagnostics.ps1 `
  -VerifyBundle "C:\Path\To\S-Talking-crash-diagnostics-....zip"
```

## Frozen CLI

```text
--crash-recovery-snapshot
--export-crash-diagnostics
--acknowledge-crash <report-id>
--verify-crash-bundle <path>
--safe-mode
```

No command installs updates, restores databases or deletes user evidence automatically.
