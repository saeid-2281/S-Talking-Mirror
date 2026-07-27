# Provider Accounts rewrite v0.19 — Phase 2

This phase makes provider catalogs account-specific and completes the first usable account-details workflow.

## Catalog ownership

The persistent voice repository remains provider-wide so favorites survive account changes. A live `VoiceCatalog`, however, is now built only from the selected API profile's remote response. This prevents voices and models from another ElevenLabs account appearing after an account switch.

The in-memory cache key includes provider, active profile ID, and credential fingerprint. Explicit refresh clears visible account data immediately and forces a remote fetch.

## Voice Browser

- Uses the active account's cached `VoiceCatalog` instead of rebuilding from the provider-wide repository.
- Clears stale voices/models while a forced refresh is in progress.
- Derives filters from the current catalog only.
- Displays the profile name rather than the raw profile ID when the main window can resolve it.

## Provider Accounts

- Selected-account refresh now forces a remote connection/catalog refresh.
- Account Details includes voice and TTS-model counts.
- Catalog counts, quota, tier, credential state, and last-check time remain profile-specific.
