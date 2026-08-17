# Roadmap 2 B6 Hotfix 3 — Hotfix 7 Hotfix 2

## Purpose

Continue from the exact failed/uncommitted Hotfix 7 + Hotfix 1 state. Hotfix 1 repaired the Hotfix 7 focused test so that a historical color token inside a non-painting QSS comment is ignored. The next focused lane exposed the same brittle raw-text assertion in the earlier Hotfix 6 primary-action regression.

## Scope

- Test-contract repair only; no production/runtime source is changed by this continuation.
- The Hotfix 6 primary-action regression now strips QSS block comments before checking that legacy `#2563EB` is absent from effective declarations.
- Hotfix 7 Hotfix 1's missing-property-safe failure diagnostics remain preserved.
- Fresh screenshot evidence is cleared before certification and exported even when pixel certification fails.

## Preserved contracts

- Hotfix 6 Provider Accounts surface repair remains unchanged.
- Hotfix 7 Main Shell surface and selected-concept primary overrides remain unchanged.
- Provider/account/voice/model/language authority remains unchanged.
- No automatic Preflight, Generation, Smart Routing or cross-provider failover is introduced.
- Credential/portable contracts and database schema 23 remain unchanged.
- Full Quality Gate runs exactly once, only after focused checks and pixel-level certification pass.
