# Roadmap 2 B6 Hotfix 3 — Hotfix 2

## Purpose

Continue from the exact failed/uncommitted B6 Hotfix 3 + Hotfix 1 state after the A11.1 monitor-width test passed alone but failed when executed after the A12 visual-certification module.

## Root cause

The runtime screenshot certifier intentionally calls `ensure_readable_runtime_font()` on the session-scoped `QApplication`. The helper rebuilt the application font from a rounded integer point size and the test fixture did not restore the incoming application font. That allowed global typography metrics to leak into later geometry tests. The monitor implementation itself is not the remaining failure: the exact A11.1 test passes in a clean process.

## Repair

- Preserve the current `QFont` metrics and change only the family when a system font must be selected.
- Do nothing when the already-selected application family is the preferred readable family.
- Snapshot and restore the shared QApplication font in the project-wide test isolation fixture.
- Keep the Hotfix 1 monitor requested-width handoff unchanged.
- Re-run the A12-certifier -> A11.1 sequence in one pytest process before the broader compatibility lane.

## Authority boundary

No provider/account/voice/model/language switching, Preflight, Generation, Smart Routing, credential storage, portable storage, recovery authority, or database-schema behavior is changed. Database schema 23 remains authoritative.
