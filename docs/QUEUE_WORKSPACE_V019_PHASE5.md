# Queue Workspace v0.19 Phase 5

This phase introduces the shared queue data-grid foundation without changing generation semantics.

## Changes

- Added a reusable queue workspace module.
- Added a compact visible/selected/scope summary bar.
- Added filename/source/text search in the current queue view.
- Standardized row height, header behavior, selection, elision, scrolling, and column sizing.
- Preserved job-identity selection across refreshes and existing scope/order rules.
- Added numeric alignment for character, duration, retry, and source-row fields.
- Added shared theme rules for the queue search, summary, table, and header.

## Scope behavior

Search affects the visible queue view. Existing explicit generation scopes remain authoritative. Users can choose the filtered-list or selected-row scope before generation.
