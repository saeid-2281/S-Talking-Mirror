# Phase 108 — Smart Routing Engine v2

Phase 108 upgrades Smart Provider Routing from the Phase 98 current-provider-versus-Piper heuristic into an explainable, deterministic, cached/configured-only ranking engine across the registered provider portfolio.

## Authority boundary

Smart Routing remains advisory. It never starts generation, never changes a cloud provider, account, voice, or model by itself, never performs cross-provider retry/failover, and never refreshes provider catalogs or billing/admin data. Preflight remains the validation authority and the Generation Engine remains the execution authority.

A Piper recommendation can still be applied only through the existing explicit **Use Piper offline** user action. A non-Piper recommendation opens the Unified Voice & Model Catalog scoped to that provider; the catalog's existing confirmation flow remains responsible for any provider/account/voice/model change.

## Evidence used

The v2 engine ranks routes using only information S-Talking already has:

- provider manifest locality and production setup policy;
- provider readiness and local runtime readiness;
- active account/profile health;
- cached/built-in voice and model catalog metadata;
- language evidence and provider certification failures;
- configured/cached cost intelligence;
- confirmed quota and quota shortfall;
- provider/model request-size limits, including UTF-8 byte limits;
- the largest job in the current generation scope;
- the user's routing preference.

Unknown cost, quota, request limits, language compatibility, or catalog state are never converted into optimistic values.

## Preferences

- **Balanced** — favors the current evidence-backed route and requires a material score advantage before recommending a switch.
- **Reliability first** — favors routes with fewer warnings and stronger readiness evidence.
- **Privacy first** — strongly favors ready local routes.
- **Lowest provider cost** — compares only known/configured cost evidence; unknown current cloud pricing cannot trigger a switch.
- **Cloud first** — keeps a ready current cloud provider unless it is blocked.

## Churn guard

A different provider is recommended only when it is ready, has sufficient language/voice/model evidence, and exceeds the current route by a material score delta. Missing catalog evidence can produce a review warning but cannot silently become a provider switch recommendation.

## Request limits

The engine evaluates the largest job rather than the total batch against per-request provider limits. Character/billed-character limits use the job character count; byte limits use the UTF-8 encoded byte count.

## Compatibility

The Phase 98 service constructor remains compatible. If Phase 106/107 intelligence services are not supplied, the service executes the legacy current-provider-versus-Piper recommendation path. This keeps historical tests and extension callers stable while the production container uses v2.

Database schema contract remains **23**.
