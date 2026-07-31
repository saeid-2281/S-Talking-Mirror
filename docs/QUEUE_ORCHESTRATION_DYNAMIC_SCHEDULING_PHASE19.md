# Queue Orchestration — Phase 19

## Dynamic Concurrency, Backpressure & Rate-Limit-Aware Scheduling

Phase 19 adds an opt-in concurrent scheduler on top of the provider failover and
adaptive routing foundation delivered in phases 17 and 18. The legacy serial
worker remains the default, so existing projects preserve their previous
execution behavior until concurrent scheduling is explicitly enabled.

## Scheduling policy

Policies can be global or project-specific and include:

- static or adaptive scheduling mode;
- minimum, initial and maximum concurrency;
- per-provider-account concurrency limit;
- success and error observation windows;
- additive concurrency recovery step;
- multiplicative backpressure factor;
- provider rate-limit cooldown.

Values are normalized before persistence. Concurrency is capped at 32, the
initial value is kept inside the configured minimum/maximum range, and the
backpressure factor is constrained to 0.1–1.0.

## Concurrent worker

When scheduling is enabled and a run has more than one pending job, the worker
uses independent provider instances in a bounded thread pool. Queue state and
SQLite job writes remain serialized in the worker coordinator thread.

The scheduler:

1. respects the adaptive routing sequence from Phase 18;
2. enforces the global and per-account concurrency limits;
3. does not submit new jobs while generation is paused;
4. allows active requests to finish during pause;
5. cancels active provider clients when Stop is requested;
6. preserves output validation and atomic writes;
7. preserves same-job provider failover;
8. stops scheduling accounts whose circuit is open or whose cooldown is active.

## Backpressure and recovery

A provider rate-limit response immediately places that account in cooldown. In
adaptive mode the global concurrency limit is reduced using the configured
multiplicative factor, never below the configured minimum. After the configured
number of successful completions, concurrency is increased by the additive
recovery step until the maximum is reached.

The worker summary records:

- scheduling mode;
- initial and maximum concurrency;
- peak observed concurrency;
- backpressure event count;
- recovery event count.

## Persistence and audit

Migration 19 creates:

- `generation_scheduling_policies`;
- `generation_provider_throttle_states`;
- `generation_scheduler_events`.

Throttle state contains the current concurrency, recent rate-limit count,
cooldown deadline and recovery timestamps for each provider account. Scheduler
events record every start, rate-limit, backpressure and recovery adjustment.
API keys and credential material are excluded from persisted metadata and
exports.

## User interface

The Generation Orchestration dialog now includes:

- **Concurrency & backpressure** policy controls;
- persistent provider throttle state;
- scheduler event history;
- current scheduling status in the execution-plan preview.

JSON and CSV orchestration exports include the scheduling policy, throttle
states and scheduler events.

## Compatibility

- Concurrent scheduling is disabled by default.
- Phase 17 failover behavior is preserved.
- Phase 18 routing behavior is preserved.
- Serial execution is used when scheduling is disabled, only one job is
  pending, or the maximum concurrency is one.
- Database schema version is 19.
