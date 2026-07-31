# Provider Accounts Pro v1.0 — Phase 6

This phase adds persisted failover order and live account health.

## Health states

- Healthy
- Degraded
- Exhausted
- Stale
- Offline
- Disabled

Health combines connection status, credentials, remaining quota, catalog freshness,
and last sync latency. The account table and details inspector expose the result.

## Failover

Manual failover order is respected when `sequence_mode` is `manual`. Manual ordering is persisted and respected. Account activation and automatic
failover are blocked while generation is active.
