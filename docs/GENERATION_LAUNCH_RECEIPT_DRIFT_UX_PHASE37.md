# Phase 37 — Generation Launch Baselines & Drift Guard UX

## Goal

Phase 37 turns the Phase 36 launch-receipt archive into an operational comparison tool. Operators can select one trusted launch receipt as the baseline for each project and compare later launches against it before reusing assumptions or investigating changes.

## Capabilities

- Persist one baseline receipt per project.
- Accept only verified or legacy receipts as baselines.
- Reject integrity-mismatch and unreadable receipts.
- Resolve, replace, and clear project baselines.
- Compare provider, model, voice, output format, file policy, execution policy, scope, retries, cost, risk, review state, acknowledgements, and integrity.
- Classify differences as critical, warning, or informational.
- Treat provider changes, output-directory changes, overwrite activation, integrity failures, and escalation to high risk as critical drift.
- Display comparison metrics in a responsive, scroll-safe dialog.
- Copy a plain-text comparison summary.
- Export secret-free JSON and Markdown drift reports.
- Preserve all Phase 35 and Phase 36 receipt contracts.

## UI

The Launch Receipts audit center now includes:

- Set as project baseline
- Clear project baseline
- Compare to baseline
- Baseline identity and integrity summary
- A dedicated Generation Launch Drift dialog with:
  - total change count
  - critical count
  - warning count
  - informational count
  - baseline and candidate identities
  - field-by-field differences
  - copy and export actions

## Persistence

The baseline index is stored under the reports directory:

```text
generation-launch-receipt-baselines.json
```

Only receipt identifiers and paths are stored. API keys, credentials, and provider secrets are never written.

## Compatibility

- No database migration.
- Schema 22 remains unchanged.
- Phase 35 legacy receipts remain readable.
- Phase 36 SHA-256 verification remains authoritative.
- Existing public handles, theme tokens, and generation button labels are unchanged.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_generation_launch_receipt_drift_ux_phase37.py
```

Expected:

```text
8 passed
```
