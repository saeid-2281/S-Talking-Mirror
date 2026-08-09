# Phase 90 — Provider Intelligence & Voice Selection UX 2.0

Phase 90 is the second product-value phase of S-Talking 1.1. It reduces the
provider/model/voice decision loop before preflight without changing provider
routing, credentials, generation semantics, or launch safety.

## Product behavior

The Provider workspace now contains a read-only **Provider intelligence** card.
It combines already-available application state into one decision surface:

- provider readiness and the last connection status,
- cached model/voice compatibility for the selected language,
- confirmed profile or cached account quota against the current generation scope,
- the existing project pricing estimate when a rate is configured,
- one explicit next action.

The card never contacts a provider by itself. Catalog refresh remains an
explicit user action and the existing Voice Browser owns that operation.

## Selection recommendation

When a cached catalog proves the current model or voice is incompatible,
Provider Intelligence can recommend a compatible cached model/voice pair.
Applying the suggestion changes only model and voice. It never automatically
switches provider, API profile, credential, language, scope, or generation
policy.

The recommendation prefers:

1. a TTS model compatible with the selected language,
2. a voice compatible with that model,
3. an exact language match when available,
4. favorite voices before non-favorites,
5. deterministic name/ID order as the final tie-breaker.

## Quota and cost

Confirmed API-profile quota has priority over cached catalog account quota.
When the selected scope exceeds known quota, the action reuses the existing
`quota_batch` scope instead of inventing a new launch path.

Cost is read from `GenerationCostCapacityService`. If no pricing policy/rate is
configured, the UI says so instead of fabricating a provider price.

## Safety boundary

Phase 90 is decision support only:

- no automatic provider switching,
- no automatic account/profile switching,
- no credential mutation,
- no live catalog/network call during passive refresh,
- no bypass of preflight, budget/quota guards, confirmations, or `MainWindow.start()`,
- no change to queue identity, provider routing, retry/failover, billing, or output policy.

## Access

- Provider workspace → **Provider intelligence**
- `Ctrl+Alt+V` → focus Provider Intelligence
- Command Palette → `Provider: Intelligence & Selection`

## Verification

Dedicated Phase 90 tests cover deterministic recommendations, language/model
compatibility, voice compatibility, profile quota precedence, quota shortfall,
cost display, no-catalog behavior, provider blockers, local/default voice
behavior, card rendering, shortcut exposure, suggestion application, and reuse
of the existing quota-sized scope.
