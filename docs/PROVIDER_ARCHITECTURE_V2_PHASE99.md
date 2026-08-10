# Phase 99 — Provider Architecture v2

## Goal

Centralize static provider metadata and UI policy before expanding S-Talking's
cloud and local provider set. Runtime adapters remain authoritative for live
capabilities and generation.

## Architecture

`ProviderManifest` describes stable, non-secret metadata: locality, credential
mode, optional dependency, setup strategy, fallback output formats, retry/live
verification flags, and provider-specific control visibility.

`ProviderRegistry` owns the ordered manifest set for the existing provider IDs:
`mock`, `piper`, `elevenlabs`, `openai`, `azure`, `google`, `aws_polly`, and
`kokoro`. It also supplies a conservative manifest for future factory-registered
providers that have not yet received a first-class manifest.

`ProviderCatalogService`, `ProviderReadinessService`, the provider workspace,
and Smart Provider Routing consume registry metadata instead of maintaining
parallel hard-coded provider sets.

## Compatibility guarantees

- Provider IDs are unchanged.
- Provider creation/factory behavior is unchanged.
- No new provider adapter is enabled in Phase 99.
- Existing ElevenLabs/Piper behavior remains authoritative.
- Phase 98 recommendation-only routing remains intact; no hidden failover is
  introduced.
- API/workspace profile files remain local-only.
- Database schema contract 23 is unchanged.

## Next phase

Phase 100 can productionize the next cloud adapters against this registry
without adding provider-ID branching to MainWindow or readiness logic.
