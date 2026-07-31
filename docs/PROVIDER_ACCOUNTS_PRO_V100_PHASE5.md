# Provider Accounts Pro — Phase 5

This phase moves account testing and catalog refresh off the UI thread.

## Added

- Independent background sync per provider profile
- Duplicate refresh prevention for the same profile
- Concurrent refresh support across different profiles
- Logical cancellation and stale-result suppression
- Per-account busy state, indeterminate progress, and cancel control
- Sync latency and result metadata stored on the profile
- Test All now queues independent profile syncs instead of blocking the dialog

Provider requests cannot always be interrupted safely. Cancel therefore releases
the UI immediately and ignores any late response from the cancelled request.
