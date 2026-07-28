# S Talking v0.20 — Application Shell Phase A

This phase makes `MainWindow` an orchestrator rather than the owner of every
top-level visual region.

## Extracted components

- `ApplicationShell`: owns the central vertical layout.
- `ProjectContextBar`: owns project identity, hidden source/output values, and
  the compact source/output controls.
- `MetricsStrip`: owns clickable queue metrics.
- `ActivityCenter`: owns Activity, Output, and Errors tabs plus collapsed and
  expanded geometry.
- `GenerationStatusStrip`: owns Start, Pause, Stop, Preflight, and progress.

The existing public `MainWindow` attributes remain as compatibility aliases so
controllers, tests, and later phases can migrate incrementally without breaking
working workflows.

## Architecture rule

New complex UI regions must be implemented in `app/gui/widgets/` and composed by
`MainWindow`. They must not be constructed as long inline widget blocks in
`app/gui/main.py`.

## Deferred to later v0.20 phases

- Queue controls and selected-row inspector extraction.
- Project Sources and Generation Monitor extraction.
- Notification Center and Activity Timeline persistence.
- Full token-driven theme and reusable component library.
