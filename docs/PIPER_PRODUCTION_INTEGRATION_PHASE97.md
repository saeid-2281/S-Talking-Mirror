# Phase 97 — Piper Production Integration

Phase 97 migrates S-Talking's existing Piper provider from CLI-per-job execution to a process-local Python runtime while preserving the normal provider factory, Queue, Preflight, retry, output, and stop contracts.

## Runtime authority

`PiperProvider` remains the provider adapter used by `create_provider()`. When the optional `piper-tts` Python API is available, it delegates synthesis to `PiperRuntimeService`. The runtime caches loaded `PiperVoice` models by model path and resolved accelerator, so repeated jobs do not reload the ONNX voice.

The runtime uses Piper's streaming Python API to produce WAV bytes in memory. The provider still returns bytes to the existing Generation Worker, which remains the authority for atomic output writes and job completion state.

## CPU / CUDA Auto

Acceleration is automatic. The runtime inspects ONNX Runtime execution providers. If `CUDAExecutionProvider` is available, Auto attempts CUDA. If CUDA model warm-up fails, Auto records the failure and falls back to CPU for the remainder of the process instead of retrying the failed CUDA load for every job.

No GPU dependency is mandatory. A CPU-only Piper installation remains supported.

## Cancellation and lifecycle

The existing `GenerationWorker.stop()` contract calls `provider.cancel()`. For the Python runtime, `PiperProvider.cancel()` sets a request-scoped cancellation event that is checked between streamed audio chunks. The legacy CLI fallback keeps the currently running process handle and terminates it on cancellation.

The Offline TTS Engines dialog exposes explicit **Warm Piper runtime** and **Restart Piper runtime** actions. They are disabled while generation is active. Warm-up loads the selected model only; it does not synthesize audio or start generation. Restart clears the selected model from the process cache; it does not alter voice files or settings.

## Safe fallback

Legacy CLI remains available only as a compatibility fallback when the Python API cannot be loaded. S-Talking does not silently re-run a failed Python-API synthesis through the CLI because that could duplicate work and obscure existing retry semantics.

## Distribution boundary

Phase 97 updates the optional Piper dependency to `piper-tts>=1.4.2,<2`, but does not bundle Piper or voice models into the S-Talking installer. Piper's current upstream project is GPL-3.0 and voice model licenses vary. Installer/bundle policy and verified voice packs remain explicit Phase 99 distribution work.

## Preserved contracts

- no database migration; schema 23 remains authoritative
- no Queue identity/order changes
- no Preflight bypass
- no hidden generation or retry from runtime controls
- existing WAV output and atomic write path preserved
- optional Piper dependency: S-Talking still launches without Piper installed
