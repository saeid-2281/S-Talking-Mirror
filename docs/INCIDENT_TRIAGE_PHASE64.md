# Phase 64 — Support Bundle Intake, Incident Triage & Remediation Readiness

Phase 64 turns the privacy-safe support bundle created in Phase 63 into a verified local triage case and a human-controlled remediation plan.

## Capabilities

- Verifies the Phase 63 support ZIP before reading structured evidence.
- Verifies the matching receipt and custody chain when supplied.
- Reads the incident summary, manifest, crash snapshot and environment without extracting the archive.
- Confirms stable version, channel, incident identity and manual-transport contracts.
- Classifies the likely component with deterministic rules.
- Calculates effective severity, P0–P3 priority and acknowledgement/remediation targets.
- Detects related verified cases through a privacy-safe deterministic fingerprint.
- Writes tamper-evident case and remediation-plan JSON records.
- Verifies case, plan, source bundle and receipt integrity after creation.
- Exposes the workflow through Reports, Command Palette, frozen CLI and PowerShell.

## Safety contract

Phase 64 never uploads a bundle, creates an external ticket, applies a patch, performs a rollback, restarts the application or publishes a release. Case creation is a dry run until explicit acknowledgement. Every remediation action is recorded with `automatic: false`, and every external or operational decision remains human-controlled.

The original support bundle remains in place. Triage records contain hashes, filenames, classification and redacted incident metadata only; databases, settings, API profiles, credentials, generated audio and project sources are never copied.

## CLI examples

```powershell
.\.venv\Scripts\python.exe -m app.frozen_main `
  --incident-triage-snapshot `
  --incident-triage-bundle <bundle.zip> `
  --incident-triage-receipt <receipt.json>
```

```powershell
.\.venv\Scripts\python.exe -m app.frozen_main `
  --create-incident-triage-case `
  --incident-triage-bundle <bundle.zip> `
  --incident-triage-receipt <receipt.json> `
  --acknowledge-incident-triage
```

```powershell
.\.venv\Scripts\python.exe -m app.frozen_main `
  --verify-incident-triage-case <case.json>
```
