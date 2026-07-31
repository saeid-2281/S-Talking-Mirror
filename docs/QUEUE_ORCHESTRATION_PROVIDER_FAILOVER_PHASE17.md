# Queue Orchestration & Provider Failover — Phase 17

Phase 17 starts the post-v1.0 orchestration epic by making named provider-account failover executable inside the real generation worker.

## Runtime behavior

1. Before generation starts, `GenerationOrchestrationService` creates an immutable execution plan from the active provider settings, named API profiles, failover order, project policy, and persisted circuit states.
2. The active account remains the first candidate unless its circuit is open. An eligible backup can become the first route when the primary account is temporarily isolated.
3. Network, rate-limit, server, authentication, and quota failures may retry the same job on the next eligible account.
4. Validation, filesystem, cancellation, and unknown permanent failures do not trigger provider failover.
5. Each candidate is attempted at most once for a job. The worker also enforces a maximum number of account switches per run.
6. A successful backup can remain sticky for the rest of the queue.

## Circuit breaker

Circuit state is stored per project, provider, and API profile. Consecutive eligible failures open a circuit after the configured threshold. Open accounts are removed from automatic routing until the cooldown expires. After cooldown, an account becomes half-open and can be probed by a real generation request. A successful request closes and resets the circuit.

## Persistence

Migration 17 adds:

- `generation_orchestration_policies`
- `generation_provider_circuit_states`
- `generation_failover_events`

Every switch, exhausted route, circuit transition, and recovery success is auditable. Circuit-open events can publish a Notification Center warning and are written to the Activity Timeline.

## User interface

`Reports > Queue Orchestration` opens the orchestration center. It provides:

- project/global policy controls;
- current execution-plan preview;
- excluded-account reasons;
- circuit state and manual reset;
- failover event history;
- JSON and CSV export.

## Safety rules

- Automatic failover requires both the project policy and provider profile failover mode to allow it.
- Disabled, credentialless, exhausted, unavailable, or open-circuit accounts are not selected.
- If every configured account is unavailable or has an open circuit, generation start is blocked with an explicit reason.
- The worker never loops indefinitely between the same accounts.
- Raw credentials are never written to the database, event history, logs, exports, or notifications.
