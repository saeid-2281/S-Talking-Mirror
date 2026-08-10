# Phase 103 — Next-Gen Cloud Providers: Cartesia + Deepgram

## Purpose

Phase 103 adds production-oriented HTTP adapters for Cartesia Sonic and Deepgram Aura without changing S-Talking's provider-selection authority:

> Smart Routing recommends; Preflight validates; the user decides; Generation executes.

No adapter introduced by this phase may silently switch to another provider or engine.

## Cartesia

S-Talking uses Cartesia's versioned HTTP API with `Cartesia-Version: 2026-03-01` and Bearer API-key authentication.

Production contract:

- live account/connection probe through the voice endpoint;
- live, paginated voice discovery;
- Danish language mapping from `da-DK` to Cartesia's `da` synthesis language;
- production model choices `sonic-3.5`, `sonic-3`, and `sonic-latest`;
- `/tts/bytes` synthesis;
- MP3 and WAV output mapping;
- optional pronunciation dictionary ID through provider options;
- speed guidance through `generation_config`;
- normalized HTTP/network/cancellation errors.

The preview-only `sonic-preview` model is intentionally not exposed as a production selection.

## Deepgram Aura

S-Talking uses Deepgram's HTTP API with `Authorization: Token <api-key>`.

Production contract:

- connection/catalog probe through `/v1/models`;
- the returned `tts` model catalog is normalized into both voice and model entries;
- selected Aura voice and model must identify the same catalog model;
- `/v1/speak` synthesis;
- MP3, WAV, Opus, FLAC, AAC and PCM mappings;
- speed validation and normalized HTTP/network/cancellation errors.

### Danish certification

Deepgram Aura is integrated as a production provider, but Danish is not certified in S-Talking in Phase 103 because the current public Aura TTS voice catalog does not document Danish voices. S-Talking therefore blocks a Danish Deepgram generation during Preflight instead of substituting another language or provider.

This is deliberately distinct from Deepgram Speech-to-Text language support.

## Provider architecture integration

The Provider Registry is extended by appending `cartesia` and `deepgram` after all previously stable provider IDs. Existing provider order remains backward-compatible.

Both providers are:

- cloud providers;
- profile-or-key credential providers;
- managed by the existing Provider Accounts infrastructure;
- retry-ready at the provider contract level;
- exposed to Voice Browser/catalog normalization;
- subject to provider-specific synthesis validation in Preflight.

Account-level connection validation remains separate from synthesis-selection validation. A user can test an API key and refresh the catalog before choosing a voice/model, while Generation remains blocked until a valid synthesis combination is selected.

## Compatibility guarantees

Phase 103 preserves:

- Database schema contract 23;
- Preflight as generation authority;
- the existing Generation Engine;
- explicit provider choice;
- no hidden cross-provider failover;
- local-only account/profile files outside Git;
- Phase 99–102 provider contracts.

## Verification

Dedicated tests cover registry/factory registration, authentication headers, Cartesia pagination and Danish payloads, Deepgram live TTS catalog normalization, output mapping, connection probes, error normalization, Danish certification gating, Preflight integration, preview extensions, provider-switch safety, and schema 23.

Phase 103 also removes the old fixed cloud-provider sets from batch planning, launch confirmation, and unified preflight decision logic. Cloud/local classification in those paths now comes from the central Provider Registry, so later provider additions do not require another synchronized list.
