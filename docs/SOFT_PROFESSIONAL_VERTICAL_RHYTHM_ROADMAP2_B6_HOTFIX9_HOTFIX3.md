# Roadmap 2 / B6 Hotfix 3 / Hotfix 9 / Hotfix 3

## Responsive disclosure visibility authority

Hotfix 9 Hotfix 2 proved that the remaining 50 px slot was not owned by
`queueRangeBar`: the range frame was absent from `QVBoxLayout`, hidden, and
zero-height while the gap remained.

The actual leak came from the independent responsive overlay callback in
`MainWindow._sync_workspace_overlay_compact()`. Both `GenerationJourneyWidget`
and `QueueBatchOperationsWidget` historically implemented
`set_compact_mode(False)` as `setVisible(True)`. A delayed resize/preset sync
therefore reopened a disclosure that A9 had already collapsed.

This continuation separates two concerns:

- presentation/disclosure intent (`set_presentation_visible`)
- temporary compact-mode suppression (`set_compact_mode`)

Leaving compact mode restores the remembered disclosure intent instead of
blindly showing the widget. Explicit user disclosure remains actionable.

The structural range-host removal from Hotfix 2 is preserved. When Batch plan
is closed, workflow, batch operations, and range controls consume no vertical
space. When Batch plan is explicitly opened, the visible order is:

`Queue heading -> Batch plan -> Range row -> Command rows`

with only compact layout spacing between rows.

No provider, routing, Preflight, Generation, credential, portable, or database
authority changes are introduced.
