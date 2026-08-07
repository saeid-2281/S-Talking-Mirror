# Phase 79 — Provider Performance Governance

Phase 79 turns existing provider reliability and verified financial evidence into
human-reviewed provider scorecards and governance recommendations.

It consumes:

- current provider reliability aggregates from the Generation Reliability service;
- verified Phase 78 financial audit records, attestations, audit packs and receipts.

## Scorecard dimensions

Each provider scorecard includes:

- session count;
- completed and failed jobs;
- success, failure and retry rates;
- average throughput;
- average health score;
- audited invoice count and amount;
- settlement adjustment amount and rate;
- final audited residual variance;
- billing accuracy score;
- reliability score;
- overall governance score;
- risk level;
- evidence-backed governance recommendation.

Recommendations are one of:

- `preferred`;
- `approved`;
- `watch`;
- `restricted`.

Insufficient reliability history or missing Phase 78 financial coverage caps a
provider at `watch`. Non-zero final audited residual variance caps the provider at
`restricted`.

## Human governance record

A governance record requires an owner, a privacy-safe review statement and human
acknowledgement. A human may choose a more conservative decision than the
recommendation, but cannot choose a more permissive state without new evidence.

## Evidence outputs

Phase 79 produces:

- provider-governance snapshot;
- governance record;
- governance attestation;
- audit pack;
- audit-pack receipt.

JSON documents, linked evidence, ZIP entries and receipts are SHA-256 protected.

## Safety contract

Phase 79 is decision support only. It never automatically:

- changes provider routing;
- disables a provider account;
- performs failover;
- changes provider cost or billing configuration;
- uploads evidence externally.

Provider routing remains controlled by the existing operational routing and policy
systems after explicit human action.
