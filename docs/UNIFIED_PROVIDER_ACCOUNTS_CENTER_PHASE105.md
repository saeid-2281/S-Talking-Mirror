# Phase 105 — Unified Provider Accounts Center

Phase 105 consolidates named cloud-provider accounts into one registry-driven management surface. It does not change generation-provider authority: selecting or activating an account only changes the active account **within that provider**. S-Talking never changes the current generation provider as a side effect of account management.

## Unified inventory

`ProviderAccountsCenterService` composes the existing `ApiProfileService` and `ProviderCatalogService` into one read-only cross-provider inventory. Managed providers are derived from `ProviderManifest.profile_management_ready` plus `controls.api_profile`; there is no second hard-coded provider list.

The center reports managed/configured provider counts, total and enabled accounts, active-provider count, accounts needing attention and exhausted accounts. Safe inventory summaries contain account names and operational state only; raw credentials and profile metadata values are excluded.

## Accounts UI

The existing Provider Accounts dialog remains the single account-management window and keeps its historical Accounts/Failover tab contract. Phase 105 adds:

- an **All managed providers** view;
- cross-provider summary metrics;
- account search by name, provider, health/status or tier;
- provider display names in the shared account table;
- provider-scoped activation semantics explained in the UI;
- registry-driven action policy for saved secrets, external credentials and metadata;
- one provider-aware account editor for account name, credential and declared safe metadata.

Google Cloud TTS and Amazon Polly continue to use external credential resolution. Their profiles do not expose Replace key or Temporary key actions. API-key providers retain secure secret replacement and temporary-key workflows.

## Ordering contract

Account priority is provider-scoped. Reordering an OpenAI account cannot renumber or reorder Azure, Google, AWS or any other provider account. This corrects the historical global-priority behavior in `ApiProfileService.move_profile()`.

The All Providers view intentionally disables manual move buttons because rows are grouped by provider; reordering is performed from a provider-scoped view.

## Failover and provider authority

Failover controls remain enabled only where the provider manifest explicitly exposes `account_failover`. Phase 105 does not enable new automatic failover behavior and does not introduce cross-provider switching.

- Account activation: scoped to one provider.
- Account failover: same-provider only, existing explicit policy.
- Smart Routing: recommendation only.
- Preflight: validation authority.
- User: provider-selection authority.
- Generation Engine: execution authority.

## Persistence and security

No database migration is introduced; schema contract 23 remains authoritative.

Raw provider credentials continue to live in `SecureCredentialStore`. `api-profiles.json` stores only named profile state and safe declared metadata. The local `api-profiles.json` and `workspace-profiles.json` files remain excluded from source commits and patch artifacts.
