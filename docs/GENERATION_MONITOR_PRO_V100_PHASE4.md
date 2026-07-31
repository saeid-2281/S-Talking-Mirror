# Generation Monitor Pro v1.0 — Phase 4

## Advanced Retry & Failure Analysis

Phase 4 adds a policy-driven retry workflow on top of the Phase 1–3 monitor,
snapshot, and recovery foundation.

### Failure analysis

- Normalizes provider and runtime errors into these categories: network, rate
  limit, server, authentication, quota, validation, filesystem, cancelled, and
  unknown.
- Stores a stable SHA-256-derived error fingerprint so repeated failures can be
  grouped even when request IDs or numeric values differ.
- Persists category, provider/error code, fingerprint, retryability, exhausted
  state, next retry time, and complete retry history per queue job.
- Adds database migration v4 and preserves the new metadata across project
  close/open and recovery snapshots.

### Retry policy

- Retry all eligible failed jobs.
- Retry selected jobs.
- Retry transient failures only.
- Retry by failure category.
- Block permanent failures by default.
- Block jobs that reached the configured maximum retry count.
- Manual override for selected jobs, with explicit confirmation.
- Deterministic exponential backoff with a maximum delay.
- Interruptible retry countdown before the next provider request.
- Prevent retry operations while generation is active.
- Record attempt start, failure, scheduling, manual override, and completion in
  each job's retry history.

### User interface

- Expanded Retry menu with policy-aware operations.
- Failure Analysis panel in Generation Monitor with retryable, permanent, and
  exhausted counts, category grouping, and top fingerprint.
- Explicit retry countdown in Generation Monitor.
- Selected-row inspector includes failure category, fingerprint, retry limit,
  and retry history count.
- Failure report export to JSON and CSV.
- Retry and export events are recorded in Activity Timeline and Application Log.

### Failure report

Failure reports are created under `reports/failures` and contain:

- Summary counts.
- Category and fingerprint groups.
- Job filename and source row.
- Error code and last safe error message.
- Retryability and exhaustion state.
- Retry count and next retry time.
- Full retry history.

### Validation

Focused tests are in:

- `tests/test_generation_monitor_pro_v100_phase4.py`

Recommended commands:

```powershell
python -m compileall app tests
python -m ruff check app tests
python -m pytest -q tests/test_generation_monitor_pro_v100_phase4.py
python -m pytest -q
powershell -ExecutionPolicy Bypass -File .\scripts\quality-gate.ps1 -Full
```
