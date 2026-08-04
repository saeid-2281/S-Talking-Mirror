# Phase 57 — Performance and Long-Run Stability

Phase 57 adds bounded process telemetry, explicit performance budgets and repeatable soak observations without copying project content, provider credentials, database rows or generated audio into evidence.

## Product surface

The desktop application exposes **Reports → Performance & Stability** and the command-palette entry **Reports: Performance & Stability**.

The center reports:

- application startup time;
- process working set (RSS);
- Python traced heap while a managed observation is active;
- process and Qt thread counts;
- live Qt and top-level widget counts;
- Windows process handle count when available;
- GC-tracked object count;
- queue size and whether generation is active;
- long-run RSS growth in MB/hour;
- completed or interrupted observation runs.

## Budget policy

The project-scoped runtime uses `performance-stability.json` in the writable settings directory. Values are normalized before persistence. The default warning/blocker budgets are intentionally conservative and can be changed without a database migration.

Background sampling defaults to once per minute and retains at most 720 samples. Sampling never runs more frequently than once every 15 seconds. The history is rewritten atomically and remains bounded.

## Startup measurement

`PerformanceStabilityService` begins its clock when the service container is created. `MainWindow` marks startup ready on the first Qt event-loop turn after construction. This captures application initialization without delaying the first visible window.

## Long-run observation

An observation can be started before a long generation or an idle soak. The service enables `tracemalloc` only for the lifetime of the managed observation when tracing was not already active. Finishing the observation records:

- duration;
- sample count;
- starting, ending and peak RSS;
- RSS and Python-heap growth;
- normalized MB/hour growth;
- status (`completed`, `cancelled`, `failed` or `interrupted`).

Closing the application finishes an active observation as `interrupted` rather than silently losing evidence.

## Command-line soak workflow

Source and frozen builds expose:

```text
--performance-snapshot
--performance-export
--performance-soak-minutes <minutes>
--performance-sample-interval <seconds>
--performance-max-samples <count>
--performance-label <label>
```

The PowerShell wrapper is:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\performance-soak.ps1 -Quick -Export
```

A production-duration observation can be run with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\performance-soak.ps1 `
  -DurationMinutes 120 `
  -SampleIntervalSeconds 30 `
  -Export
```

The workload is intentionally synthetic and bounded. It does not load projects, call providers, generate audio, mutate queues or install updates.

## Privacy contract

Samples and exports contain process counters only. Labels are capped, restricted to safe characters and redact API-key, token, password, credential, authorization and bearer assignments. The service never reads or copies:

- project source text or filenames;
- API profiles or credential stores;
- settings content;
- SQLite rows;
- generated audio or output files;
- provider responses or cache content.

## Evidence paths

```text
<artifacts>/performance-stability/samples.jsonl
<artifacts>/performance-stability/runs.json
<artifacts>/performance-stability/runs/*.json
<artifacts>/performance-stability/latest-snapshot.json
<artifacts>/performance-stability/exports/*.json
<artifacts>/performance-stability/exports/*.csv
```

## Release acceptance

Phase 57 is accepted when:

1. dedicated tests pass;
2. the full suite and Quality Gate pass;
3. a quick soak completes and exports evidence;
4. startup, working-set, thread, widget and handle budgets are visible;
5. sample retention remains bounded;
6. no private project or credential content appears in any evidence;
7. the working tree is clean after commit and push.

Database schema remains **22**.
