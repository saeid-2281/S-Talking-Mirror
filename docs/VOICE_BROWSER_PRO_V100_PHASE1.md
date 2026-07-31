# Voice Browser Pro — Phase 1

This phase migrates the main voice catalog from `QTableWidget` to Qt's
Model/View architecture without changing the existing preview or provider
workflow.

## Added

- `VoiceTableModel` based on `QAbstractTableModel`.
- `VoiceTableView` based on `QTableView`.
- Stable voice identity lookup by provider voice ID.
- Selection restoration after search, filter, model, or catalog refresh.
- Compatibility helpers for existing tests and transitional call sites.
- A live result/favorite count in the filter bar.
- Smooth pixel scrolling and a compact professional data-grid presentation.
- Regression and 10,000-voice scalability tests.

## Preserved

- All voices, Favorites, and Recent tabs.
- Existing search and metadata filters.
- Model compatibility filtering.
- Favorites, preview generation/cache, saved previews, and account context.
- The public `dialog.table.selectRow()`, `rowCount()`, `currentRow()`, and
  `item().text()` read contracts during migration.
