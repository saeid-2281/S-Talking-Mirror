# Phase 89 — Generation UX 2.0

Phase 89 starts the S-Talking 1.1 product-value track after the completed 1.x
infrastructure certification. It does not add another governance surface.

## Goal

Reduce the number of places a user must inspect before starting a batch. The
main queue workspace now contains a persistent **Generation Journey** that
summarizes the five practical steps:

1. Source
2. Provider
3. Voice
4. Scope
5. Preflight

A context-sensitive primary action always routes to the next useful step:
prepare text, fix provider setup, choose a voice, choose a scope, run/review
preflight, or review and start generation.

## Safety boundary

Generation UX 2.0 is presentation and navigation only. It does **not bypass
preflight, confirmation, baseline guard, budget/quota guard, output policy,
approval operations, safe-resume validation, or provider validation**.
`MainWindow.start()` remains the only launch path and continues to run the
existing authoritative preflight and confirmation services before generation.

The Journey does not duplicate provider business rules. It projects the
existing `ProviderReadinessService` result and caches that result until the
provider configuration signature changes.

## Product behavior

- The journey updates as sources, provider settings, scope, preflight and
  generation state change.
- The active scope shows both job and character counts.
- The Provider and Voice steps route directly to the existing provider workspace
  and Voice Browser.
- The Source step opens the existing Text Studio.
- The Preflight step uses the existing Dry Run / Preflight workflow.
- `Ctrl+Alt+G` focuses the workflow from anywhere in the application.
- Compact/focus layouts collapse the step row and retain only the headline and
  next action, preserving vertical space.
- Existing Generation menu actions, toolbar controls and Command Palette remain
  available.

## Non-goals

Phase 89 does not change queue ordering, generation scope semantics, provider
selection, synthesis behavior, retry behavior, persistence, billing, evidence
schemas, release state, or production certification.
