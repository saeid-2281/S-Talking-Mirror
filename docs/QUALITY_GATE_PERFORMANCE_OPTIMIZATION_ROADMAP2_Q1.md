# Roadmap 2 Q1 — Quality Gate Performance Optimization

## Purpose

Reduce S-Talking validation latency without deleting tests, weakening release evidence,
or changing production runtime behavior.

## Execution model

The full test suite is partitioned into two lanes:

1. **Parallel-safe allowlist** — audited non-Qt test files are distributed across
   independent Python/pytest processes. Each process receives a unique `--basetemp`
   and JUnit output.
2. **Serial-sensitive lane** — Qt/PySide6/pytest-qt, QProcess, unknown/new tests,
   subprocess/release tooling, shared reports/artifacts, and other repository-level
   side effects remain serial on Windows.

Unknown test files default to the serial lane, so future tests are never silently
parallelized before review.

## CPU policy

`auto` uses 60% of logical processors, capped at 8 workers. `all` is supported for
explicit benchmarking, and a positive integer selects an exact worker target up to
the logical CPU count.

Using every logical processor is not the default because Qt processes, filesystem
I/O, antivirus scanning, and Windows scheduling can make full saturation slower or
less stable.

## GPU policy

Generic pytest, Qt, filesystem, database, and QProcess tests are CPU-bound. The
orchestrator reports CUDA availability but does not schedule generic tests on the GPU.
GPU execution is reserved for future tests that explicitly exercise CUDA/inference
workloads.

## Coverage and evidence

No test file is dropped. The explicit parallel allowlist plus the serial fallback
covers every discovered `tests/test_*.py` file. Each lane emits JUnit evidence, which
is aggregated into a machine-readable performance report with pass/skip/failure
counts and the slowest tests.

## Compatibility

- `scripts/quality-gate.ps1 -Full` uses the optimized runner.
- `-LegacyFull` or `S_TALKING_LEGACY_FULL_GATE=1` restores the historical serial path.
- `scripts/release-check.ps1` uses the same optimized pytest runner while retaining
  the existing release-check result schema and `steps.pytest.passed` contract.
- Database schema remains 23.
- Provider GA, Preflight, Generation, routing, recovery, and plugin authority are
  unchanged.

## Performance artifacts

The normal full quality gate writes:

`artifacts/quality-gate-performance/latest.json`

The report includes CPU topology, selected worker count, lane sizes, total wall time,
aggregate testcase time, pass/skip/failure counts, CUDA visibility, and the slowest
testcases.

## Hang safety and observability

Parallel workers emit a heartbeat every 20 seconds, report completion as soon as
each worker finishes, and have a 1200-second per-worker timeout. On interruption
or timeout, the runner terminates the complete worker process tree. The serial lane
also emits heartbeat messages so a long Qt/release test is never a silent wait.

## Hotfix 5 — Hybrid lanes

The broad parallel model was measured on the 28-logical-CPU Windows workstation and
did not provide enough benefit: the conservative serial lane dominated wall time.
Q1 therefore uses a hybrid model:

- strict pure/isolated tests: up to 6 workers;
- UI/MainWindow/Qt tests: exactly 2 workers;
- QProcess/release/shared-state tests: hard serial;
- pure and UI-limited workers overlap;
- historical JUnit testcase timings from the previous run are used to balance shards.

The optimization target is wall-clock duration, not CPU utilization. Qt event-loop,
timer, filesystem, and subprocess waits are not CPU-bound, so forcing all logical
processors is explicitly not the default.

## Hotfix 7 — Per-file UI process isolation

The two-worker UI shard experiment was rejected after the Windows benchmark showed
cross-process QSettings registry interference and a 1200-second worker timeout.
The pure lane itself completed in roughly 22–26 seconds, so CPU sharding is retained
only where it is demonstrably safe.

The UI lane now uses one test file per fresh Python process with at most four concurrent
slots. Every isolated UI process receives a unique QSettings IniFormat path through a
temporary `sitecustomize.py`, preventing implicit MainWindow settings reads/writes from
sharing the Windows registry.

Twenty-one tests that explicitly exercise QSettings or provider-profile stores remain
serial with native semantics. QProcess, release, subprocess, and unknown tests remain
hard serial. Historical JUnit data is scanned across recent runs, not just the latest
possibly partial run, so long-running UI files are scheduled first.

The goal remains wall-clock reduction with deterministic isolation, not artificial CPU
utilization.
