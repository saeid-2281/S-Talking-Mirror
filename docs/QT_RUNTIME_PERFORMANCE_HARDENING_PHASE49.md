# Phase 49 — Performance & Qt Lifecycle Hardening

Phase 49 centralizes top-level report-dialog ownership in a weak registry. It removes strong-reference signal callbacks, marks dialogs for delete-on-close, exposes runtime health diagnostics, and drains deferred deletion safely during shutdown.

## Runtime health signals

- registered active and hidden dialogs
- top-level and visible widget counts
- global thread-pool activity
- peak dialog concurrency
- created, finished, and destroyed totals
- stale weak-reference detection

The **Reports → UI Runtime Health** workspace can refresh the snapshot, close hidden dialogs, flush deferred deletes, and export a JSON diagnostic report. No source text, API credentials, or provider secrets are collected.

## Compatibility

Public report-dialog handles remain available through `MainWindow.report_dialogs`. Existing dialog geometry, theme tokens, queue controls, and button text are unchanged. Database schema remains version 22.
