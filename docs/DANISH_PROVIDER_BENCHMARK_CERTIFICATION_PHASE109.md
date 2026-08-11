# Phase 109 — Danish Provider Benchmark / Certification

## Purpose

Phase 109 separates three concepts that must not be conflated:

1. **Documented Danish support** — vendor/runtime documentation says Danish is supported.
2. **Runtime readiness** — the provider/account/model/voice can actually be used by S-Talking.
3. **S-Talking Danish certification** — a human reviewed the fixed Danish corpus for a specific provider/voice/model and the evidence passed the certification threshold.

Documented support alone never creates a quality certification.

## Fixed corpus

The Phase 109 corpus contains 12 deterministic Danish cases covering everyday speech, numbers, dates, compound words, Danish place names, abbreviations, question prosody, long-form narration, dense Danish phonetics, names, code switching and punctuation.

Each case is scored from 1–5 for:

- intelligibility
- pronunciation
- prosody
- stability

At least 10 cases are required. Certification requires an overall score of at least 80/100, no critical case dimension below 3, and documentation state `documented` or `runtime_dependent`. Scores from 70 to below 80 remain `conditional`. Lower scores or critical failures are `not_certified`.

## Current documentation evidence reviewed 2026-08-11

- ElevenLabs: Danish documented for multilingual TTS models.
- OpenAI Speech: Danish documented; built-in voices are documented as optimized for English, so quality remains benchmark-dependent.
- Azure Speech: Danish (Denmark) text-to-speech is documented.
- Google Cloud TTS: Danish (Denmark) voices are documented, including Chirp 3 HD.
- Amazon Polly: Danish voices are documented.
- Piper: the maintained Piper voice catalog documents `da_DK`; certification remains voice-pack specific and MODEL_CARD licensing remains authoritative.
- Kokoro: S-Talking keeps Danish blocked because the certified Kokoro runtime language set does not include Danish.
- Cartesia Sonic 3.5: Danish (`da`) is explicitly documented.
- Deepgram Aura TTS: current TTS voice/language documentation does not include Danish, so S-Talking keeps it not certified.
- Resemble: Danish (`da-dk`) is documented in the SSML locale contract.
- Murf Gen2: multilingual TTS is documented, but the reviewed model page does not explicitly enumerate Danish as a model-level contract; S-Talking keeps Danish certification pending until benchmark evidence and the TTS contract are reviewed together.

## Safety and authority

Phase 109 never:

- synthesizes audio automatically,
- refreshes a provider catalog automatically,
- calls billing/admin APIs,
- changes the selected provider/account/voice/model,
- launches generation,
- performs cross-provider retry or failover.

The reviewer explicitly chooses the provider/voice/model, generates/listens to samples through the normal S-Talking workflow, enters ratings, and saves certification evidence. Smart Routing v2 may consume **only verified Phase 109 certification evidence** for Danish language scoring. It still recommends; the user decides; Preflight validates; Generation Engine executes.

## Evidence storage

Evidence is stored under:

`artifacts/danish-provider-benchmark/`

Certification JSON is payload-hashed. A modified or malformed latest record is ignored and treated as pending rather than trusted.

## Database

No database migration is introduced. Database schema contract remains **23**.
