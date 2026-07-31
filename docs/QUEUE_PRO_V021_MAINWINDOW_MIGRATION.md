# Queue Pro v0.21 — MainWindow migration

This phase connects the real `QueueTableView` to `MainWindow` behind a reversible
feature flag while keeping the existing `QTableWidget` implementation as the
production fallback.

## Enable the new queue

Set the environment variable before launching S Talking:

```powershell
$env:S_TALKING_QUEUE_MODEL_VIEW = "1"
.\scripts\run.ps1
```

Use `0` to force the legacy queue. When the variable is absent, the optional
`QSettings` key `features/queue-model-view` is read; its default is disabled.

## Migrated interactions

Both implementations now use `QueueViewAdapter` for selection, current job,
identity-safe row lookup, scrolling, context-menu coordinates, double-click,
and incremental row refresh. `MainWindow.render_queue()` delegates model data to
`QueueTableModel` when Model/View is enabled and retains the established legacy
renderer otherwise.

The new path updates status rows through `dataChanged` during generation when the
visible identity sequence is stable. A filter or sort change triggers a safe
model reset and restores selection by job identity.

## Rollback

No data migration is required. Set `S_TALKING_QUEUE_MODEL_VIEW=0` and relaunch to
return to the legacy table immediately.
