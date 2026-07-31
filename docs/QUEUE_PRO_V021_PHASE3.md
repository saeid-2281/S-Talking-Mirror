# Queue Pro v0.21 — Phase 3

This phase improves the queue presentation without changing generation rules.

## Column presets

The Columns menu now includes task-oriented presets:

- Compact
- Generation
- Review
- All columns

A preset controls visibility, order, and practical widths. Filename and Status
remain structural and cannot be hidden. The selected preset and resulting header
state are persisted through QSettings.

## Progress rendering

The status delegate now renders a supplied running progress value as both a
filled badge and readable text such as `Running · 42%`. When the provider does
not expose intermediate progress, the normal Running badge remains unchanged.
