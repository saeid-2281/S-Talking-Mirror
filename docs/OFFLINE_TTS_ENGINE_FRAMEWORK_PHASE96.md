# Phase 96 — Offline TTS Engine Framework

Phase 96 introduces a read-only local-runtime inventory and configuration authority for S-Talking 1.1.

## Scope

- Register the current local providers (`piper`, `kokoro`) as offline engines.
- Detect optional Python runtimes and the legacy Piper CLI without importing heavy runtime modules.
- Discover Piper `.onnx` voices from the selected model folder and known local voice roots.
- Parse adjacent `.onnx.json` metadata for language, sample rate and speaker count.
- Expose engine/runtime/voice health through one dependency-injected service.
- Add **Settings → Offline TTS Engines** and **Ctrl+Shift+L**.
- Allow an explicit user action to select a discovered Piper model in the existing Provider panel.

## Safety and compatibility contract

Phase 96 does **not**:

- download or install Piper/Kokoro packages;
- download voice models;
- start a local HTTP server or persistent runtime process;
- synthesize audio;
- change queue, preflight, retry, billing, output, or recovery semantics;
- introduce a database migration;
- replace `PiperProvider` or its legacy CLI execution path.

The Offline TTS Engine service is read-only. Voice selection is an explicit UI action and is disabled while generation is active.

## Piper direction for Phase 97

The current upstream Piper project supports a Python API (`PiperVoice.load`, `synthesize_wav`, streaming synthesis) and optional CUDA execution. Phase 97 can therefore replace per-job CLI model loading with a managed runtime host while preserving the existing `piper` provider identity and generation contract.
