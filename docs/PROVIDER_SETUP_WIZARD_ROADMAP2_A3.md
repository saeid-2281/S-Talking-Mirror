# Roadmap 2 / Track A / A3 — Provider Setup Wizard

## Goal

Provide a guided first-time provider setup flow without weakening the production
provider authority established in Phases 98–112.

## Guided flow

1. Choose a provider intentionally.
2. Select a named provider account or keep the current temporary/external credential context.
3. Validate credentials explicitly in Provider Accounts and optionally refresh only the selected provider catalog using an explicit button.
4. Choose voice, model and language from cached/built-in metadata or enter identifiers manually.
5. Review cached cost, quota and request-limit context.
6. Finish with an explicit confirmation that applies provider/account/voice/model/language choices.

## Safety contract

Opening or navigating the wizard does not:

- change the active generation provider;
- activate a provider account;
- probe a provider;
- refresh a provider catalog;
- run Preflight;
- start or restart generation;
- apply Smart Routing;
- perform hidden cross-provider failover.

Provider catalog contact happens only after **Refresh provider catalog** is pressed and
confirmed. Credential validation remains an explicit **Test** action in Provider Accounts. Final provider/account/voice/model changes happen only after **Apply
setup choices** is pressed and confirmed.

Credential creation/editing remains in Provider Accounts. Offline local-model setup
remains in Offline TTS Engines. The wizard composes those existing production tools
rather than creating a second credential or engine authority.

## Preflight and generation boundary

The wizard never calls Preflight and never starts generation. After setup is applied,
S-Talking explicitly tells the user to run the existing connection test and Preflight.
The Generation Engine remains the only execution authority.

## Persistence and schema

A3 adds no database migration and does not persist wizard progress. Existing settings
are written only by the normal MainWindow settings path after the explicit Finish
confirmation. Database schema remains **23**.

## Onboarding integration

The A2 provider-readiness step now hands off to the Provider Setup Wizard. The A2
six-step checklist, persistence format and completion rules remain unchanged.

## Q2 quality-gate baseline

A3 is based on Q2 commit `1e7403af8aded8ffbe6694a9f06d899d10b67b78`.
The stable serial profiled Full Quality Gate and test-only runtime fast path remain the
authoritative end-of-phase gate; experimental parallel pytest remains opt-in only.
