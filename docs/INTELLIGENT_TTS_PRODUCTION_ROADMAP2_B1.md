# Roadmap 2 B1 — Intelligent TTS Production Foundation

## Certified baseline

B1 starts from the A12.1 + Hotfix 4 certified baseline:

`c41a7e4f28865cf1640173c4c10a29adc5659839`

The A8–A12.1 visual redesign is frozen. B1 does not alter the three-theme
System / Light / Dark contract or the Soft Professional surface hierarchy.

## Purpose

B1 introduces a real production-code boundary for deterministic TTS request
planning: `IntelligentTTSProductionService`.

The service compiles the current queue plus the operator-selected settings into
an immutable `ProductionManifest`. It is intentionally separate from execution
so later B phases can consume one explicit, auditable request contract instead
of rediscovering provider/model/voice/language choices while a run is active.

## Authority contract

B1 preserves all existing production authority:

- provider is copied exactly from the supplied settings;
- API profile/account id is copied exactly when present;
- voice and model are copied exactly;
- default language is copied exactly;
- a per-job language change is accepted only through the explicit
  `job_language_overrides` mapping;
- text content is never used for language detection;
- input queue order is never changed;
- retry count is recorded only for the selected provider;
- cross-provider failover is explicitly recorded as disabled;
- B1 never runs Preflight;
- B1 never starts/restarts Generation;
- B1 never applies Smart Routing;
- B1 never creates a provider;
- jobs/settings are never mutated.

## Production intelligence

For each queue row the manifest records:

- deterministic request id and request signature;
- source row / filename / output destination;
- provider/profile/voice/model/language authority;
- text character count and SHA-256;
- same-provider retry limit;
- duplicate output collision signals;
- unsafe filename/path signals;
- empty, short-utterance and large-text review signals.

These signals are advisory. B1 never silently renames a file, segments text,
changes language, changes provider, or changes execution order.

Consecutive requests with the same exact request signature are represented as
**observational batches**. This metadata is for later throughput/execution
integration only and does not reorder or execute queue items.

## Privacy-safe evidence

Normal manifest serialization excludes raw source text and never includes API
keys. Raw text serialization exists only as an explicit opt-in API for future
trusted execution integration.

Certification evidence is written to:

`artifacts/intelligent-tts-production/roadmap2-b1/`

with:

- `certification.json`
- `manifest-example.json`

## Exit criteria

B1 completes only after:

- 14 dedicated B1 tests pass;
- B1 certification reports `CERTIFIED`;
- provider/routing authority regressions pass;
- queue/generation planning regressions pass;
- language-lock/pronunciation regressions pass;
- A7 launch/Track A acceptance regressions pass;
- A12.1 three-theme regression passes;
- historical DevCheckRunner QProcess regression passes;
- Database schema 23 remains unchanged;
- one Full Quality Gate passes on the final source;
- exact B1 files are committed and pushed;
- source Working Tree is clean excluding local-only profile files.

## Next

After B1, Roadmap 2 continues with B2 Intelligent TTS Production execution
integration, consuming this manifest without weakening the authority boundary.
