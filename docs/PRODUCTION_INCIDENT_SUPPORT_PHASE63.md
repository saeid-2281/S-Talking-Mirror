# Phase 63 — Production Incident Response & Privacy-Safe Support Bundles

Phase 63 adds a local production incident intake and support evidence workflow on top of the verified Phase 62 post-GA maintenance baseline.

## Capabilities

- Verifies the stable application identity and Phase 62 baseline.
- Verifies structured crash report integrity before collection.
- Collects recent text logs with credential and local-path redaction.
- Excludes databases, settings, API profiles, credentials, project sources and generated audio.
- Enforces a reviewed bundle size budget.
- Writes a ZIP manifest and external SHA-256 receipt.
- Verifies bundle and receipt integrity after creation.
- Exposes the workflow through Reports, Command Palette, frozen CLI and PowerShell.

## Safety contract

Phase 63 never uploads, emails, publishes, installs, restarts, cleans or deletes anything. Bundle creation requires explicit acknowledgement. Sharing remains a separate manual action after reviewing the bundle and receipt.

## CLI examples

```powershell
.\.venv\Scripts\python.exe -m app.frozen_main `
  --incident-support-snapshot `
  --incident-summary "Generation stops after queue resume while the interface remains responsive." `
  --incident-severity high
```

```powershell
.\.venv\Scripts\python.exe -m app.frozen_main `
  --create-incident-support-bundle `
  --incident-summary "Generation stops after queue resume while the interface remains responsive." `
  --incident-severity high `
  --acknowledge-incident-support
```

```powershell
.\.venv\Scripts\python.exe -m app.frozen_main `
  --verify-incident-support-bundle <bundle.zip>
```
