# Generation Monitor Pro v1.0 — Phase 5

## Session History & Performance Analytics

Phase 5 turns completed generation batches into a searchable historical archive.
It builds on the live monitor, recovery, and retry/failure-analysis foundation
from Phases 1–4.

### Persisted session telemetry

Database migration v5 extends `batch_sessions` with:

- Total, active, and paused duration.
- Retry-event count.
- Files per minute and characters per minute.
- Failure summary grouped by category and fingerprint.
- Complete sanitized monitor metrics.

Existing session records remain compatible and receive safe default values.

### Generation History window

The Reports menu now includes **Generation History** with:

- Current-project or all-project scope.
- Result and provider filters.
- Search across session ID, provider, model, voice, and generation scope.
- Historical totals, completion rate, retries, average elapsed time, and
  throughput summary.
- Per-session details including output/report paths and failure categories.
- Open report, open output, and copy report path operations.

### Run comparison

Selecting two sessions compares the older session with the newer session and
shows deltas for:

- Completion rate.
- Elapsed time.
- Files per minute.
- Characters per minute.
- Retry events.
- Failed jobs.

### Export

Filtered history can be exported to JSON and CSV under `reports/history`.
Exports include the aggregate summary, all visible session telemetry, failure
summaries, and sanitized monitor metrics.

### Validation

Focused tests are in:

- `tests/test_generation_monitor_pro_v100_phase5.py`

Recommended commands:

```powershell
python -m compileall app tests
python -m ruff check app tests
python -m pytest -q tests/test_generation_monitor_pro_v100_phase5.py
python -m pytest -q
powershell -ExecutionPolicy Bypass -File .\scripts\quality-gate.ps1 -Full
```
