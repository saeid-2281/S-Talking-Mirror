# Roadmap 2 / B8.2B Stage 3B-1 — Startup Sweep Isolation

## Evidence and scope

Stage 3A runtime evidence recorded a roughly 144-second deferred startup with the Qt GUI thread in `StartupRecoveryService.clean_stale_temporary_audio()` and `Path.rglob()`. Other evidence showed an ~19-second first project open and a later project-open action that did not complete during the trace. This patch addresses the confirmed startup file-sweep hot path **only**. It does not certify project switching, Piper, final receipts, ledger integrity or runtime responsiveness.

## Product behavior

- Synchronous `StartupRecoveryService.recover()` retains its original cleanup contract for existing API callers and tests.
- The MainWindow path calls `recover(defer_temporary_cleanup=True)` so database migration, interrupted-job reset, and settings/recent-project checks still complete **before** session restoration. These database operations may still take time; moving database work to another thread is outside this patch.
- On ordinary GUI startup, only temporary files older than 24 hours with suffixes `.tmp`, `.part`, `.partial` are considered by a cancellable daemon filesystem worker. It does **not** delete `.wav` or `.mp3` files or recently modified temporary files. Neither Qt widgets, database connections, settings nor profile data are used by the worker.
- A Qt signal transfers only a count or generic failure to the GUI thread. Closing the window sets the cancellation event; no join, busy-wait or Qt event-loop nesting is introduced.
- The original full sweep remains available to explicit synchronous callers; the new GUI startup uses the safer age-gated scope.

## Limits / gates

B7 stays frozen; existing explicit provider, account, voice, model, language, routing, generation and Preflight controls stay unchanged. No schema changes. This patch does not install or migrate Piper and does not modify persisted model/view feature flags. The Windows runtime acceptance diagnostic should explicitly run the source with `S_TALKING_QUEUE_MODEL_VIEW=1`, so its queue architecture matches the portable baseline; legacy mode remains separately available for regression tests.

Run focused tests and the full quality gate on the exact Stage 3A working tree. Inspect the resulting log before any commit/push or portable build. Repeat real GUI startup, representative large-queue/project-switch, generation and final receipt/ledger tests separately. No completion or certification is claimed until they pass.
