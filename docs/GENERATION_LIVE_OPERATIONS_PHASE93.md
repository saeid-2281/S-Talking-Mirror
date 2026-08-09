# Phase 93 — Generation Run & Live Operations UX 2.0

Phase 93 improves the operator experience during and immediately after a generation run without changing generation, retry, billing, queue ordering, or preflight semantics.

## Run focus

The existing Generation Monitor now contains a compact **Run focus** card. It derives its state from the existing generation controller and `GenerationMonitorService.state` and shows:

- processed / total progress;
- completed, pending, and failed counts;
- current filename;
- ETA and average completed-job duration;
- ETA confidence (`low`, `medium`, `high`) based only on completed-job sample size;
- retryable failure count and retry-event count;
- current run id;
- latest completed output handoff.

No new background timer, worker, provider call, billing path, or generation path is introduced.

## Existing command routing

All actions route to commands that already own mutation semantics:

- **Pause / Resume** → `MainWindow.pause()`;
- **Stop** → `MainWindow.stop()`;
- **Retry transient** → `MainWindow.retry_transient()`;
- **Open latest output** → existing output playback handoff;
- **Review failures** → existing Generation Monitor failure summary.

The live-operations service is read-only. It never starts, pauses, stops, retries, reorders, or mutates jobs.

## Completion handoff

When a run completes, the same card becomes the post-run decision surface. The operator can immediately open the latest completed output or review failures. Partial and failed runs remain explicit; retry actions remain governed by the existing retry policy.

## Accessibility and discovery

- `Ctrl+Alt+R` focuses Generation Live Operations.
- Command Palette exposes `Generation: Live Operations`.
- The toolbar overflow includes `Generation Live Operations`.
- Status and action availability remain keyboard accessible.

## Safety contracts

Phase 93 preserves all established contracts:

1. no new generation launch path;
2. no change to preflight or confirmation;
3. no change to billing reservation or reconciliation;
4. no change to retry eligibility or retry limits;
5. no change to queue identity or execution order;
6. no automatic retry after completion;
7. no automatic output playback.
