# Queue Pro v0.21 Phase 2.3 — Compatibility Adapter

`QueueViewAdapter` provides one job-identity API for both the current
`QTableWidget` and the new `QueueTableView`.

MainWindow now uses the adapter for selection, preview, session restoration,
row navigation and context-menu positioning. Rendering remains on the legacy
widget in this phase, so generation and playback behavior stay unchanged.

The next migration step can switch the concrete view behind the adapter without
rewriting these interactions again.
