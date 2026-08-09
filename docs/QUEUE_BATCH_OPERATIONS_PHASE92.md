# Phase 92 — Queue & Batch Operations UX 2.0

Phase 92 adds a read-only Batch Lens to the Queue workspace. It accelerates large-batch selection without changing job identity, queue ordering, execution ordering, retry policy, or generation safety.

## Batch Lens

The lens can select all visible, pending, failed, current selection, or the pending prefix that fits the currently cached quota. Selection is always expressed as existing `row_number` identities through `QueueViewAdapter`.

## Analytical grouping

Status, provider, and voice grouping are summaries only. Grouping never reorders the table or generation plan.

## Bulk actions

The compact menu routes to the existing Retry Failed, Skip Selected, Reset Selected, and Clear Completed commands. Phase 92 introduces no new mutation semantics.

## Compact contract

The Batch Lens hides in Compact and Focus Mode, preserving the queue-dominance layout contract. It remains available on demand through `Ctrl+Alt+Q`.
