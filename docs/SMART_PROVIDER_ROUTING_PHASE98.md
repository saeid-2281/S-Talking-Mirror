# Phase 98 — Smart Provider Routing & Offline/Cloud Fallback

## Goal

Phase 98 adds a **read-only routing recommendation** between the provider already configured for the project and the configured Piper offline route.

It does **not** add runtime failover between providers.

The generation authority remains:

`Provider settings → Preflight → Launch confirmation → Generation`

## Routing preferences

The Provider workspace exposes four explicit preferences:

- **Balanced** — keep a ready configured provider; show Piper as the offline fallback.
- **Privacy first** — recommend configured Piper when it is ready.
- **Lowest provider cost** — recommend Piper only when the configured cloud provider has a confirmed positive provider cost. Unknown cloud pricing does not trigger a switch.
- **Cloud first** — keep the currently configured cloud provider while it is ready. The router never invents another cloud provider or restores hidden credentials/model/voice state.

The preference is stored in `QSettings`, not the project database. Database schema 23 is unchanged.

## Availability and quota

The router uses existing authorities only:

- `ProviderReadinessService` for configured-provider readiness.
- confirmed active API-profile quota when available.
- `OfflineTTSEngineService` for Piper runtime/model/config readiness.
- `GenerationCostCapacityService` for configured cloud-provider cost estimates.

There are no network probes in ordinary routing refresh.

If the configured provider is blocked or confirmed quota is too small, and Piper is ready, the router can recommend **Use Piper offline**.

## Applying a recommendation

A recommendation never mutates provider settings by itself.

The user must press **Use Piper offline**. MainWindow then reuses the existing `apply_offline_piper_voice()` path, which:

1. verifies the `.onnx` model and `.onnx.json` config still exist,
2. selects provider `piper`,
3. selects `piper-local` and the configured voice,
4. invalidates preflight,
5. requires the user to run preflight/start normally.

No generation, retry, queue mutation, or playback starts from the routing card.

Provider changes are blocked during an active generation run.

## No hidden fallback contract

Phase 98 deliberately does not implement:

- Cloud → Piper switching during a run,
- Piper → Cloud switching during a run,
- automatic retry on another provider,
- automatic profile/key switching between different provider families,
- automatic voice/model conversion between providers,
- automatic generation after applying a recommendation.

Existing ElevenLabs account-profile failover remains separate and unchanged.

## Scope

Phase 98 adds only product-layer routing analysis and UI wiring. It does not change database schema, GenerationWorker semantics, Queue identity/order, Preflight rules, budget/billing guards, Piper synthesis runtime, or output handling.
