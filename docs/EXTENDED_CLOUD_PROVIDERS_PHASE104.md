# Phase 104 — Extended Cloud Providers: Resemble + Murf

Baseline: Phase 103 (`926ef4b43108eaca5866cb1c411b7620bc953887`)

## Scope

Phase 104 adds production-oriented cloud adapters for:

- `resemble` — Resemble AI synchronous Text-to-Speech
- `murf` — Murf Gen2 non-streaming Text-to-Speech

The architectural law remains unchanged:

> S-Talking never silently changes provider/engine. Smart Routing recommends;
> Preflight validates; the user decides; Generation Engine executes.

No database migration is introduced. Schema contract 23 remains authoritative.

## Resemble

Implementation uses the current documented HTTP surfaces:

- API/voice metadata: `https://app.resemble.ai/api/v2/voices`
- synchronous synthesis: `https://f.cluster.resemble.ai/synthesize`
- authentication: `Authorization: Bearer <api-key>`
- synchronous response audio: base64 `audio_content`
- output formats used by S-Talking: WAV and MP3

Resemble chooses the synthesis model from the selected `voice_uuid`; S-Talking
therefore exposes `resemble-ultra` as an informational voice-managed model entry
but never sends a `model` field in the synthesis request.

The current Resemble SSML locale table explicitly documents Danish (`da-DK`).
When a language is selected, plain text is safely escaped and wrapped in a
`speak` element with `xml:lang`. Existing SSML is passed through unchanged.
Actual language quality/availability remains voice-dependent.

Numeric S-Talking speed is intentionally not approximated into Resemble's
qualitative SSML speed tags. Phase 104 requires speed `1.0` for this adapter
instead of silently producing a different delivery than the UI requested.

## Murf

Implementation uses the current non-streaming Gen2 API:

- voice catalog: `GET https://api.murf.ai/v1/speech/voices?model=gen2`
- synthesis: `POST https://api.murf.ai/v1/speech/generate`
- authentication: `api-key: <api-key>`
- model: explicit `GEN2`
- `encodeAsBase64=true` so S-Talking receives audio directly instead of
  depending on a generated CDN URL
- supported S-Talking output formats: MP3, WAV, FLAC, OGG and PCM
- supported sample rates: 8000, 24000, 44100 and 48000 Hz

The public Murf documentation dated at this phase states that legacy Gen2
*streaming* is scheduled for deprecation on 2026-08-16, while Gen2 remains
available through the non-streaming Synthesize Speech endpoint. Phase 104 does
not use the deprecated streaming route.

Murf Danish (`da-DK`) remains explicitly certification-gated because the current
public Gen2/Falcon 2 documentation does not explicitly document Danish. A live
voice catalog can still expose provider-supported locales for browsing, but
S-Talking will not claim Danish production certification until the provider
contract is independently verified.

## Shared integration

Both providers are registered in:

- Provider Registry / stable provider ordering
- Provider Factory
- Provider Accounts / named profile workflow
- Provider Identity service
- Voice Browser catalog normalization
- preview output-extension mapping
- synthesis-specific Preflight validation
- registry-driven generation planning/confirmation inherited from Phase 103

No new hidden failover path is introduced. Neither adapter owns or references a
fallback provider.

## Verification expectations

Phase 104 automation runs:

1. exact Phase 103 baseline/remote/hash verification
2. `git diff --check`
3. `compileall`
4. Ruff on the exact Phase 104 Python scope
5. schema authority guard (`23`)
6. dedicated Phase 104 tests
7. Phase 96–103 provider-track compatibility tests
8. Provider Accounts / Voice Browser / Preflight / Planning / Generation focused regression
9. historical DevCheckRunner QProcess regression
10. Full Quality Gate
11. exact staging, commit, push and remote verification

Local-only `api-profiles.json` and `workspace-profiles.json` remain uncommitted.
