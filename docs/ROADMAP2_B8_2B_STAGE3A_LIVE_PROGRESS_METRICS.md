# Roadmap 2 B8.2B — Stage 3A / live progress metrics and row lookup

Source baseline: `1bd9e05fd42302a8b0f009b50ca2d76043fbdc1a`.
B7 stays frozen. Apply patch at the project root **only** on the matching baseline.

## Verified code path and scoped change

The controller receives one GUI-thread progress signal per job. Previously each
controller metrics/scoped_metrics call performed a SQLite average-duration query,
including during every live progress event and dashboard repaint. This adds a
potentially blocking database reader *on top of* the still-synchronous per-job
project repository write. Its `_job_index` lookup also linearly rescanned the
entire queue on each signal.

- When `GenerationController.is_active`, both public metrics methods use the
  *already-loaded* job durations to estimate remaining time; they do not ask the
  project repository for another SQL average. Outside generation, the historical
  persisted average is unchanged. Counts, statuses, worker events and row scope
  remain unchanged. Live ETA can differ slightly from the historical project-
  wide SQL average when queue filters exclude previous completed jobs.
- Build a row-number index once at generation start and use a safe fallback scan
  for a missing or stale index. Clear it on project/queue reset and completion.
- No worker, provider, generation-start, queue mutation, DB schema, B7 code,
  run-ledger status/finalization, sidecar or receipt code is modified.

## What this stage does NOT claim

This is a limited GUI hot-path reduction, **not** an async database persistence
conversion or a fix for the measured long per-job SQLite *writes*, output
hashing, execution-session finalization, or the final receipt. The fresh Windows
full quality gate and real large-queue Piper/Provider Accounts manual acceptance
must be completed before commit, push, a Portable rebuild or declaring B8.2B
complete. A green unit test on another operating system cannot substitute.

## Run

1. Extract the **single delivery ZIP** at `D:\Projects\S-Talking`, preserving
   paths. Do not copy old local credentials into a new project.
2. Double-click `RUN-B82B-STAGE3A-TESTS.cmd` at the project root. It verifies the
   baseline, runs compile, Ruff, stage-specific tests, B8 stage 1/2 regression
   tests, then the stable serial full Quality Gate. No commit/push occurs.
3. On Windows, repeat the *same* large-queue Pause/Resume/Stop and final receipt
   scenario from the B8.2A/B8.2B diagnostic instructions, using the existing
   external GUI heartbeat and opt-in trace. Check that no evidence is missing
   and note stalls separately. Send `C:\zip-for-GPT\S-Talking-B82B-Stage3A-last-run.txt`
   and sanitized heartbeat/trace files if manual acceptance fails.
4. Commit/push only after **both** the full gate and manual evidence pass, in
   accordance with the existing project handoff protocol. Rebuild Portable only
   from the certified pushed commit.

Runner logs are timestamped and the most recent transcript is retained as
`last-run.txt`, including on failure. The ZIP includes only changed/new files;
local profiles, settings, accounts, keys and audio are never included.
