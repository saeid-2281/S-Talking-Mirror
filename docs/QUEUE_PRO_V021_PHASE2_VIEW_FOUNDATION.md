# Queue Pro v0.21 — Phase 2 View Foundation

This phase introduces `QueueTableView`, a `QTableView` shell backed by the new
`QueueTableModel`.

The production MainWindow still uses the established `QTableWidget` path. The
new view is intentionally introduced behind tests first so selection,
context-menu, playback and generation behaviour can migrate incrementally.

Implemented compatibility features:

- row selection and keyboard shortcuts;
- selection persistence by stable job identity;
- select/scroll by job id;
- QTableWidget-like `itemSelectionChanged` and `cellDoubleClicked` signals;
- model/view column sizing prepared for the current 12-column queue.

The next migration step will move queue rendering and selection reads behind a
small adapter consumed by MainWindow before the old widget is removed.
