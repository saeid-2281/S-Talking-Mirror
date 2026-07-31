# Text Studio Professional v0.24 — Phase 3

Phase 3 improves daily editing and portability without changing the queue import contract.

## Added

- Internal drag-and-drop reordering for one or multiple chunks.
- Multi-row smart splitting.
- Enable/disable selected chunks.
- Bulk document-section actions: all, none and invert.
- Portable session export/import with atomic JSON writes.
- Session schema version 3, while retaining compatibility with versions 1 and 2.
- Preservation of enabled states during reordering and session round trips.

Text Studio continues to emit only enabled `TextSourceEntry` objects through the existing normalized CSV/import pipeline.
