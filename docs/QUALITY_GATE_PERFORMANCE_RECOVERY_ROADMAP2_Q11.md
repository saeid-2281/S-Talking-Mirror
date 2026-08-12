# Roadmap 2 / Q1.1 — Quality Gate Performance Recovery

## Decision

Q1 proved that broad CPU parallelization is safe only for a small pure-test lane.
The final isolated-hybrid benchmark was correct but slower than the historical serial
baseline on the Windows workstation.

Official Q1 benchmark evidence:

- 1552 tests
- 1551 passed
- 1 skipped
- 0 failures
- 0 errors
- 2292.363 seconds total wall time
- 1147.527 seconds parallel/UI phase
- 1144.555 seconds serial-sensitive phase

Q1.1 therefore restores a stable serial Full Quality Gate as the default.

## Default behavior

`scripts/quality-gate.ps1 -Full`

runs:

`scripts/serial_pytest_profile.py`

The profiler executes one normal serial pytest process and preserves:

- full test coverage;
- JUnit evidence;
- total wall time;
- aggregate testcase time;
- top 25 slow tests;
- machine-readable JSON.

Default report:

`artifacts/quality-gate-performance/serial-latest.json`

## Experimental parallel behavior

The Q1 isolated-hybrid runner is retained unchanged for controlled benchmarking only.

Explicit opt-in:

`./scripts/quality-gate.ps1 -Full -ExperimentalParallel`

or:

`S_TALKING_EXPERIMENTAL_PARALLEL_GATE=1`

The worker-count argument remains available only for that experimental path.

## Legacy raw serial behavior

The pre-profiler raw serial path is retained for diagnosis:

`./scripts/quality-gate.ps1 -Full -LegacyFull`

or:

`S_TALKING_LEGACY_FULL_GATE=1`

## Release Check

Release Check follows the same policy:

- default: serial profiled pytest;
- `-ExperimentalParallel`: Q1 isolated-hybrid runner;
- `-LegacyPytest`: raw serial pytest.

Its existing result schema and `steps.pytest.passed` parser remain compatible because
the serial profiler emits a normal `<N> passed` summary.

## Architectural impact

Q1.1 changes quality infrastructure only.

It does not change:

- production application behavior;
- provider/engine authority;
- Smart Routing;
- Preflight;
- Generation Engine;
- provider failover behavior;
- database schema 23.

## Next optimization track

Future runtime gains should come from reducing the cost of slow UI tests themselves:
MainWindow construction, Qt timers/waits, repeated container bootstrap, QSettings,
filesystem setup, and other wait-bound fixtures.

Parallel worker-count tuning is no longer the default optimization strategy.
