# Queue Orchestration — Phase 20

## Predictive Queue Planning & Deadline-Aware Scheduling

Phase 20 adds a project-aware completion forecast before generation begins. It uses persisted routing telemetry when enough history exists and falls back to a configurable conservative throughput rate otherwise.

## Policy

A global or project-specific deadline policy controls:

- target completion window in minutes;
- warning slack before the target;
- whether an at-risk queue may raise initial concurrency;
- maximum concurrency allowed for deadline protection;
- fallback characters-per-minute estimate;
- forecast safety margin;
- forecast persistence.

Deadline planning is disabled by default, preserving Phase 19 behavior.

## Forecast

For each queued run the planner records:

- job and character counts;
- current and recommended concurrency;
- effective characters per minute;
- estimated duration and completion time;
- configured deadline and remaining slack;
- risk score and risk level;
- recommendation and estimate source.

Risk levels are `on_track`, `watch`, `at_risk`, `missed`, and `insufficient_data`.

## Deadline protection

When deadline planning and automatic boost are enabled, an `at_risk` or `missed` forecast may increase the execution plan's initial concurrency before the worker starts. The result remains bounded by the deadline concurrency cap and is divided across available provider profiles.

Disabling automatic boost keeps generation serial or at the existing Phase 19 concurrency while still exposing the risk and recommendation.

## Audit and export

Forecasts are stored in `generation_queue_forecasts` when persistence is enabled. The orchestration JSON and CSV exports include the effective deadline policy and queue forecast history. Credential-like metadata is filtered before persistence or export.

## Database

Migration 20 adds:

- `generation_deadline_scheduling_policies`;
- `generation_queue_forecasts`;
- project, risk, and creation-time indexes.

Before an existing database receives migration 20, the database layer creates a verified `.pre-v20.bak` backup.
