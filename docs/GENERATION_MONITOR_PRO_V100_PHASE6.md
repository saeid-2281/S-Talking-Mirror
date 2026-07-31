# Generation Monitor Pro v1.0 — Phase 6

## Performance Baselines & Regression Alerts

Phase 6 turns the session archive from Phase 5 into an active performance guardrail. Every completed generation run is scored and compared with a rolling baseline made from comparable successful sessions.

## Comparable baseline

A session is compared only with historical sessions that use the same:

- project
- provider
- model
- voice
- generation scope

The rolling baseline uses the most recent successful comparable sessions and median values to reduce sensitivity to outliers. At least three sessions are required before regression alerts are enabled.

## Metrics

- completion rate
- failure rate
- seconds per processed job
- files per minute
- characters per minute
- retries per 100 jobs
- overall health score from 0 to 100

## Regression policy

Phase 6 detects warning and critical regressions for:

- throughput drops
- increased processing time per job
- completion-rate drops
- failure-rate increases
- retry-rate increases
- failed session results

The analysis stores the baseline session, baseline metrics, metric deltas, severity, reasons, and health score in the project database.

## Product integration

- automatic analysis after a batch session is recorded
- warning or critical Notification Center entry
- Activity Timeline event with analysis metadata
- Health and Regression columns in Generation History
- filter by critical, warning, healthy, or insufficient-baseline state
- rolling trend summary
- manual baseline recalculation for imported or older history
- JSON and CSV export of all performance fields

## Database

Migration version 6 adds performance-analysis fields and indexes to `batch_sessions`. Database backup behavior from previous migrations remains active.
