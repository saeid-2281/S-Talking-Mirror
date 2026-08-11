# Phase 110 — User-Controlled Multi-Provider Recovery

## Purpose

Phase 110 adds a controlled recovery handoff after provider failures without introducing hidden cross-provider failover.
The generation worker keeps its existing provider-scoped account failover behavior; cross-provider recovery is a separate
operator flow and always requires explicit human action.

## Recovery sequence

1. A failed or partial run leaves failed jobs unchanged.
2. **Generation → Multi-Provider Recovery** builds an assessment from failed/pending jobs and Smart Routing v2 evidence.
3. Assessment is cached/configured-only: no catalog refresh, connection probe, billing query, synthesis, or provider switch occurs.
4. The user selects an alternate route.
5. Cloud routes open the Unified Voice & Model Catalog; provider/account/voice/model changes use its existing explicit confirmation.
6. Piper opens the offline-engine review path; the user must select/confirm a local voice pack.
7. **Prepare selected route** requires another explicit confirmation, writes a tamper-evident recovery receipt, resets failed jobs to pending, and runs Preflight.
8. Generation is still not started. The user must review Preflight and press Start Generation manually.

## Safety invariants

- No automatic cross-provider switch.
- No automatic generation restart.
- No hidden cross-provider retry/failover.
- Same-provider account failover remains the only worker-level failover mechanism.
- Smart Routing recommends; Unified Catalog / Offline Engines reviews; Preflight validates; User decides; Generation Engine executes.
- Recovery receipts contain route identifiers and row numbers, not API keys or secrets.
- Database schema remains 23.
