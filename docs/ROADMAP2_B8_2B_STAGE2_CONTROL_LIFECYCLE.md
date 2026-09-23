# Roadmap 2 B8.2B — Stage 2 / Pause-Stop audit IO isolation

Baseline: a7a8f241e6f9cbb1847774c73c8bd3382f275c42 on
`roadmap2/b8-gui-responsiveness-evidence`. Frozen B7 stays unchanged.

Scope
- Retain the immediate Worker pause/stop event and the tiny atomic
  `generation-lifecycle.json` sidecar on the GUI thread.
- Serialize the potentially large integrity-verified run-ledger status files
  on a single worker thread (not the Qt GUI event loop).
- Queue terminal ledger finalization behind every status event in FIFO order;
  no terminal transition can overtake a queued Pause/Resume/Stop.
- Preserve fully synchronous legacy/test-fast-path lifecycle behavior and the
  original ledger schema, status transitions and hash-chain verification.
- Keep asynchronous completion errors visible in the application log without
  printing exception contents, secrets, CSV data or project paths.
- Keep queued writes running when a Qt window is destroyed; no queued evidence
  is cancelled by the GUI close operation.

Boundaries
- This stage does not move the per-job SQLite repository write, queue
  aggregates, execution-session finalization or output hashing / receipts off
  the GUI event loop. These remain candidates for the following stages.
- The final receipt may still stall the window after Stop; this stage must not
  be marked Manual Accepted based only on automated tests.
- No provider/account/voice/model/language changes, Preflight/Generation
  initiation, hidden failover, database schema change or B7 frozen changes.

Acceptance
Run Windows Dedicated + Focused + Full Quality Gate and real Piper/Provider
Accounts checks in fresh Portable; then repeat the identical large-queue
Pause, Resume and Stop scenario with the GUI Heartbeat. Verify final ledger
integrity after Stop and completion. Mark manual responsiveness separately.
