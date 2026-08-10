# Phase 102 — Local Engine Productionization (Piper + Kokoro)

Phase 102 completes the current local-engine track without changing Queue, Preflight, retry, output-write, or provider-selection authority.

## Piper model management

Piper remains the production local provider established in Phase 97. Phase 102 adds an explicit local model manager on top of the existing persistent Python runtime:

- a Piper voice must contain both `<voice>.onnx` and `<voice>.onnx.json`;
- **Import Piper voice…** copies only a user-selected local voice into S-Talking's managed `data/offline-voices/piper/<voice-id>/` root;
- copied model/config bytes are SHA-256 verified;
- an adjacent `MODEL_CARD` is preserved when present so upstream licensing information stays with the imported voice;
- conflicting managed content is never silently overwritten;
- inventory remains read-only and does not create the managed root until the user explicitly imports a voice;
- managed roots are scanned recursively, so imported voice folders become normal Piper candidates;
- no automatic voice download is introduced.

Piper synthesis still uses `PiperRuntimeService`, model reuse, cooperative cancellation, CPU/CUDA Auto selection, and the existing legacy CLI compatibility fallback. S-Talking does not silently replay a failed Python-API request through another provider or engine.

## Kokoro runtime certification

Kokoro is now a real local runtime adapter rather than a placeholder. The runtime:

- uses the official `KPipeline` API;
- caches one pipeline per certified language code;
- serializes access to each cached pipeline;
- emits 24 kHz mono PCM WAV through the existing Generation Worker byte contract;
- honors S-Talking speed, timeout, and cooperative cancellation contracts;
- exposes the official Kokoro v1.0 voice catalog to the Voice Browser only when the optional runtime is installed;
- requires an explicit compatible voice before synthesis;
- never silently changes the requested language or voice.

### Certified language set

S-Talking follows the official Kokoro v1.0 language/voice catalog:

- American English (`a`)
- British English (`b`)
- Spanish (`e`)
- French (`f`)
- Hindi (`h`)
- Italian (`i`)
- Japanese (`j`)
- Brazilian Portuguese (`p`)
- Mandarin Chinese (`z`)

American/British English are two pipelines for one language family. Japanese and Mandarin may require the corresponding Misaki extras provided by the Kokoro ecosystem.

**Danish is not in the official Kokoro v1.0 language catalog.** `da` / `da-DK` therefore fail configuration certification and cannot enter Kokoro generation. This is intentional; Phase 102 does not infer Danish support from generic espeak availability.

## Central local-output policy

Phase 102 moves forced local WAV output into `ProviderManifest.forced_file_extension`. `mock`, `piper`, and `kokoro` declare `.wav` once in the provider registry. Queue, Worker, Preflight, Report, Provider Verification, and Voice Preview consume this policy instead of maintaining separate hard-coded provider sets.

This ensures Kokoro WAV bytes cannot be written to an `.mp3` path and keeps future local providers from requiring another set of scattered conditionals.

## Dependency boundaries

- Piper stays optional and uses the existing `piper-tts>=1.4.2,<2` project contract.
- Kokoro is pinned to the official v0.9.4 API line: `kokoro>=0.9.4,<1`.
- Kokoro upstream declares Python `>=3.10,<3.14`, which includes S-Talking's Python 3.13 runtime.
- No model weights are bundled into the S-Talking distribution by this phase.
- Piper voice licenses vary; preserved `MODEL_CARD` content remains the voice-specific license authority.

## Preserved architectural law

**S-Talking never silently changes provider/engine. Smart Routing recommends; Preflight validates; User decides; Generation Engine executes.**

Phase 102 does not add cross-provider failover, hidden retries, automatic downloads, database migrations, or a new generation path. Database schema 23 remains authoritative.

## XTTS status

XTTS/Coqui remains evaluation-only. Phase 102 does not register an XTTS provider, does not add it to the Provider Registry, and does not alter the current certified provider set.
