# Phase 106 — Unified Voice & Model Catalog

Phase 106 establishes one normalized, account-scoped catalog surface for provider
voices and TTS models without changing generation authority.

## Contracts

- Catalog browsing is cached-first and performs no implicit network calls.
- Provider refresh is explicit and limited to one selected provider.
- Active named account metadata/credentials are resolved provider-by-provider.
- Credentials and provider options from the current provider are never carried into
  another provider while browsing the unified catalog.
- Cross-provider selection requires an explicit user-approved provider change.
- Same-provider selection from a different named account also requires explicit account-change approval.
- Search/filtering spans provider, profile, type, language, voice/model ID and metadata.
- Voice/model compatibility validation now applies to every provider when catalog
  metadata is available, rather than only ElevenLabs.
- MainWindow model dropdowns consume the unified catalog service. Static provider model
  contracts are centralized there; account-specific live catalogs take precedence.
- Deepgram remains live-catalog-driven because Aura model IDs are voice/model specific.
- Existing Voice Browser remains the provider-specific preview/favorites surface.
- Database schema remains 23.
- Smart Routing remains recommendation-only; catalog discovery never changes provider.

## UI

`Voice & Model Catalog` is available from Settings and the command palette with
`Ctrl+Alt+V`. The dialog opens in an All Providers cached view. Refresh is disabled until
one provider is selected, preventing accidental multi-provider network activity. Using an
item from another provider requires an explicit switch confirmation and is blocked while
generation is active.
