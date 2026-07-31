# Queue Pro v0.21 Phase 2 — Model Foundation

This phase introduces `QueueTableModel`, a read-only `QAbstractTableModel` adapter over
`TTSJob` sequences. It intentionally does **not** replace the production
`QTableWidget` yet.

## Why this is incremental

The current main window, queue selection, context menu and generation controller
still depend on `QTableWidget` APIs. Replacing them in one step would combine data,
selection and presentation risks. The new model can now be tested independently and
adopted behind a `QTableView` in the next phase.

## Capabilities

- Stable job identity through the existing `row_number` contract.
- Twelve queue columns with display, tooltip, accessibility and typed sort roles.
- Optional output-path and per-job progress snapshots.
- O(1) job-id to row lookup.
- Incremental single-row updates through `dataChanged`, without model reset.
- A 10,000-job regression test that verifies no `QTableWidgetItem` allocation is
  needed by the model layer.

## Next migration step

Introduce a `QueueTableView` behind a compatibility adapter, then move selection and
rendering consumers away from `QTableWidget` one at a time.
