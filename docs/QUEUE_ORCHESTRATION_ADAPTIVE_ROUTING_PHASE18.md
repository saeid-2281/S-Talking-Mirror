# Queue Orchestration & Provider Failover — Phase 18

Phase 18 adds opt-in adaptive routing and deterministic load balancing on top of the Phase 17 failover and circuit-breaker runtime.

## Compatibility

The default routing policy remains disabled and uses legacy priority order. Existing projects therefore keep Phase 17 behavior until adaptive routing is explicitly enabled.

## Routing modes

- **Priority** keeps the active account first and uses backups only after eligible failure.
- **Weighted** distributes jobs using each API profile's `routing_weight` metadata, with profile priority as a safe fallback.
- **Adaptive** scores every eligible account from health history, remaining quota, EWMA request latency, configured priority, and circuit state.

## Queue planning

Before generation starts, the controller passes the pending jobs into the orchestration planner. The planner produces a deterministic weighted schedule and a predicted per-account distribution. `max_profile_share_percent` limits concentration while still allowing a feasible schedule for small queues.

Profiles can be excluded when they are disabled, missing credentials, unavailable, exhausted, have an open circuit, or fall below the configured minimum quota reserve.

## Runtime telemetry

Each planned assignment creates a routing decision. Every completed or failed provider attempt updates a persisted metric containing:

- attempts, successes, and failures;
- rolling health score;
- EWMA latency;
- processed characters;
- last selection, success, and failure timestamps.

Normal routing decisions do not create Notification Center noise. Circuit-open and failover events retain the Phase 17 notification and Activity Timeline behavior.

## Persistence

Migration 18 adds:

- `generation_adaptive_routing_policies`
- `generation_provider_routing_metrics`
- `generation_routing_decisions`

A verified `.pre-v18.bak` backup is created before migration.

## User interface

The orchestration dialog now includes:

- adaptive-routing policy controls;
- current score and predicted distribution preview;
- routing health metrics;
- per-job routing decision history;
- circuit and provider-event history;
- JSON and CSV export.

## Safety

- Adaptive routing still requires automatic failover to be enabled.
- Raw API credentials are never persisted in routing metrics, decisions, exports, notifications, or logs.
- Planned account changes do not consume the failover-switch limit.
- Runtime-open circuits are skipped even when they appear in a precomputed schedule.
