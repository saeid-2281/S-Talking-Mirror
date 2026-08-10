# Phase 100 — Core Cloud Provider Productionization I

Baseline: Phase 99 Provider Architecture v2 + Hotfix 1 (`875ce3c2b4e5325c7bf8829951844ea39c76db11`).

## Scope

Phase 100 turns the existing OpenAI Speech and Azure Speech provider entries into production-oriented adapters while preserving the Phase 98 rule that S-Talking never performs a hidden cross-provider switch.

### OpenAI Speech

- Uses the existing `/v1/audio/speech` adapter for synthesis.
- Performs a non-synthesis model-access probe for connection testing.
- Preserves the supported model/voice catalog already exposed by S-Talking.
- Supports built-in and custom voice identifiers, provider instructions where the selected model supports them, and normalized output MIME handling.
- Converts timeout, transport, authentication, rate-limit and request failures into safe `ProviderError` / `ProviderNormalizedError` contracts.
- Keeps cancellation best-effort and lets the generation controller remain authoritative for final job state.
- Does not infer quota or cost when the provider has not supplied confirmed usage data.

### Azure Speech

- Keeps the optional `azure-cognitiveservices-speech` SDK boundary established by the provider registry.
- Stops treating the source language as the Azure resource region.
- Stores safe `region` / `endpoint` metadata with the selected API profile while the resource key remains in the secure credential store.
- Builds `SpeechConfig` from subscription + region or subscription + HTTPS endpoint.
- Normalizes the Azure voice catalog, locale information and output format selection.
- Produces escaped SSML with explicit language/voice/rate metadata.
- Adds best-effort SDK cancellation and normalized safe provider errors.

## Provider profile metadata

`ProviderManifest.profile_metadata_fields` is the authority for safe provider-specific account metadata. `ApiProfileService.apply_profile()` replaces only those declared account fields in `AppSettings.provider_options`, preserves unrelated runtime provider options, and never passes operational account metadata such as sync state, voice counts or timestamps into provider configuration.

The account catalog and in-memory voice catalog identities include `provider_options`, so a region or endpoint change cannot silently reuse a catalog captured for a different Azure resource.

The Provider Accounts dialog exposes only providers whose manifest declares `profile_management_ready=True`. Phase 100 enables this for ElevenLabs, OpenAI Speech and Azure Speech. Google Cloud TTS and Amazon Polly remain registered for the next productionization phase without being presented as completed profile-management integrations yet.

## Compatibility and safety

- Existing stable provider IDs and ordering are unchanged.
- Existing ElevenLabs account failover remains provider-local only.
- OpenAI/Azure do not gain automatic cross-provider fallback.
- Database schema contract remains version 23.
- Raw credentials are not written to profile metadata, project files, documentation, tests or patch artifacts.
- Existing local-only `api-profiles.json` and `workspace-profiles.json` remain outside Git scope.
