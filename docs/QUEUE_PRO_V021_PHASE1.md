# Queue Pro v0.21 — Phase 1

This phase turns the queue's visual structure into an independent workspace
without moving generation business rules out of their existing services.

## Added

- `QueueWorkspace` shell with a clear heading, range bar, command bar, summary,
  table body, and compact footer.
- Persistent column chooser.
- Movable queue columns while preserving identity-safe sorting in the existing
  controller flow.
- Semantic status badge delegate with optional progress rendering.
- Queue footer showing visible jobs, character total, selection and active scope.
- Regression tests preventing the queue container from moving back into
  `MainWindow`.

## Compatibility

Existing `MainWindow` attributes (`table`, `queue_search`, filters, scope and
range controls) remain available. Generation, Preflight, reporting, selection,
context-menu and execution-order behavior are unchanged.
