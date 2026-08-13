# Roadmap 2 / A7.1 — Language Lock & Provider Language Enforcement

## Baseline

Official A7 + Hotfix 3 commit:

`0f5579ba365143f615217212d009204aacf2fb6c`

## Product contract

The user-selected target language is authoritative.

S-Talking does not use automatic text-language detection to replace that selection.
A per-job `language_override`, when explicitly present in imported/project data, is the
only job-level override and is applied before every provider synthesis request.

The provider adapter may normalize only the syntax of the language token (for example,
`da-DK` to `da` where an API requires a base language code). It cannot choose another
provider, account, voice, model, or target language.

## Provider enforcement evidence

A7.1 introduces a deterministic Language Assurance model with four levels:

- `strong` — explicit provider parameter, SSML locale with verifiable voice match, or
  explicitly language-bound model;
- `bounded` — the request carries language/locale evidence but the selected voice or
  provider contract remains authoritative;
- `best_effort` — instruction-based or provider-detection-dependent enforcement;
- `none` — no verified enforcement mechanism.

Known language/voice/model mismatches block Preflight. Best-effort/none cases remain
visible warnings and require launch acknowledgement rather than silently switching a
provider/model.

## Important provider examples

- Cartesia: explicit base-language parameter.
- ElevenLabs: explicit language token except that the current multilingual_v2 contract
  is treated as best-effort rather than falsely certified as a hard lock.
- Deepgram Aura: language is model-bound and mismatches are blocked.
- Azure: target locale is carried in SSML and locale-coded voice mismatches are blocked.
- Google: explicit language code plus selected voice is treated as bounded.
- Amazon Polly: selected voice remains authoritative; requested locale is recorded as
  bounded assurance.
- OpenAI modern speech models: S-Talking adds a pronunciation/locale instruction derived
  from the explicit user language while preserving existing user instructions; legacy
  tts-1/tts-1-hd remain non-enforceable and are surfaced as warnings.
- Resemble: SSML locale is enforced within the documented locale contract, while voice
  language remains authoritative.
- Murf: explicit locale parameter with existing provider validation.

## Per-job execution safety

Both serial and concurrent GenerationWorker paths now resolve `job.language_override`
(or the project language) into provider-specific request settings before pronunciation
preparation and synthesis.

Preflight freshness now includes `language_override`, so changing a job language makes
the previous Preflight stale.

## Deliberate boundary with A7.2

A7.1 does **not** normalize short text, numbers, dates, currencies or acronyms and does
not perform post-generation language detection. Those controls belong to:

**A7.2 — Short-Utterance & Pronunciation Hardening**

## Invariants

- no automatic provider change;
- no automatic account change;
- no automatic voice/model change;
- no automatic target-language detection override;
- no automatic Preflight;
- no automatic generation;
- no Smart Routing apply;
- no hidden cross-provider failover;
- database schema remains 23.
