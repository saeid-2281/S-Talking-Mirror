# Roadmap 2 B6 Hotfix 3 — Hotfix 7 Hotfix 1

## Purpose

Continue from the exact failed/uncommitted Hotfix 7 state. Hotfix 7 stopped in its own focused regression before runtime screenshot certification because the test searched raw QSS text for the historical primary color token and therefore matched a non-painting explanatory comment.

## Scope

- Test-contract repair only; no production/runtime source is changed by this continuation.
- The Hotfix 7 primary-action regression now removes CSS/QSS block comments before asserting that the historical primary color is absent from effective declarations.
- The continuation runner handles certification diagnostics defensively when older/stale JSON lacks the Hotfix 7 `diagnostics` member.
- Review screenshots/certification from previous attempts are cleared before new certification, then fresh evidence is exported even if pixel certification fails.

## Preserved contracts

- Hotfix 6 Provider Accounts surface repair remains unchanged.
- Hotfix 7 Main Shell surface and selected-concept primary overrides remain unchanged.
- Provider/account/voice/model/language authority remains unchanged.
- No automatic Preflight, Generation, Smart Routing or cross-provider failover is introduced.
- Credential/portable contracts and database schema 23 remain unchanged.
- Full Quality Gate runs exactly once, only after focused checks and pixel-level certification pass.
