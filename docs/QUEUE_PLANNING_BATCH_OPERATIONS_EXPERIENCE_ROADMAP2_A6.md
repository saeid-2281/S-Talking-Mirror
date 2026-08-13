# Roadmap 2 / Track A / A6 — Queue Planning & Batch Operations Experience

## Baseline

Official A5 commit:

`947a545a3289ceb16132318ed968ea5a255b1d8f`

A5 certified Text / Source Preparation, explicit queue handoff, no automatic Preflight,
no automatic generation and schema contract 23.

## Product goal

A6 productizes queue planning without creating a second generation scheduler.

The existing Phase92 `QueueBatchOperationsService` remains read-only. Existing queue
commands and `row_number` identities remain authoritative.

## Batch plan preview

The Batch Lens is presented as **Batch plan**.

Changing the lens now updates a read-only preview containing:

- lens name;
- number of jobs in that lens;
- character count.

Changing the lens does not select rows, change generation scope, reorder the queue,
run Preflight or start generation.

`Select preview rows` remains a separate explicit action. It only changes current table
selection.

`Use selection as scope` remains another separate explicit action. It is disabled when
nothing is selected.

## Scope authority

When the user explicitly converts the current selection into generation scope:

- existing selected `row_number` identities are used;
- Preflight is invalidated because scope changed;
- Preflight is not run automatically;
- generation is not started or restarted.

An empty selection cannot replace the current generation scope.

## Bulk action availability

A6 does not add new mutation semantics. Existing Phase92 actions are retained:

- Retry failed;
- Skip selected;
- Reset selected;
- Clear completed.

The menu now disables actions whose prerequisite is absent. This prevents no-op or
contextless bulk commands while preserving the original command handlers.

## Invariants

A6 never:

- changes provider/account/voice/model;
- applies Smart Routing;
- reorders queue or execution order through grouping;
- performs hidden cross-provider failover;
- runs Preflight automatically;
- starts or restarts generation automatically.

Database schema remains **23**.
