# Roadmap 2 / B8.2B / Stage3B-3 — Compact Batch Focus Stability Hotfix

## Trigger

The permanent Queue Header performance repair passed its dedicated and focused lanes, but the
single Full Quality Gate reported one failure:

`tests.test_queue_batch_operations_phase92::test_phase92_compact_workspace_hides_batch_lens`

The failing assertion showed that an explicit `focus_queue_batch_operations()` request opened the
Batch-plan disclosure, but a pending debounced responsive refresh could run immediately afterward
and collapse the compact accordion again.

## Repair

Before explicit Batch-plan focus is revealed, `MainWindow.focus_queue_batch_operations()` now
forces the responsive coordinator to settle its current presentation signature. The coordinator
stops its pending debounce timer while refreshing. Batch-plan disclosure and lens focus then run
after that settled layout, so a stale compact refresh cannot undo the user-requested focus.

This does not change normal compact-mode behavior: compact workspace entry still starts with all
advanced accordion sections collapsed. It only makes an explicit keyboard/command focus request
authoritative after responsive layout settles.

## Preserved boundaries

- Permanent Queue Header performance changes are unchanged.
- Queue scope, ordering and generation semantics are unchanged.
- No automatic Preflight or Generation is introduced.
- No provider/account/voice/model/language authority changes.
- No hidden cross-provider failover.
- Database schema 23 unchanged.
