# Roadmap 2 / Track A / A7 — Preflight Decision & Launch Readiness Experience

## Baseline

Official A6 commit:

`e4f714e5358caeff7bca83dedc617886adc55c22`

A7 makes Preflight a required explicit validation boundary before launch review.

## Current-Preflight contract

`PreflightService.current_state()` returns cached Preflight evidence only when jobs,
settings, output directory, CSV path and project identity still match the resolved
request. The lookup is side-effect free.

## Launch authority

Generation Start does not run Preflight or refresh quota implicitly. Missing or stale
Preflight blocks launch and focuses the explicit Preflight control.

The Preflight dialog is review-only and no longer exposes a misleading Start generation
action.

Visible desktop launches always pass through a final Generation Launch Review showing
Preflight revision, settings revision, unified decision trace, provider, voice, model,
language, scope, planning, quota/cost, output and guard evidence.

Generation begins only after **Start reviewed generation**.

## Language groundwork

A7 includes language in the launch fingerprint and resolved-request review so that
A7.1 can enforce Language Lock and provider-specific language controls without changing
the launch-authority model.

## Invariants

- no automatic provider/account/voice/model/language change;
- no automatic Smart Routing apply;
- no automatic Preflight from Start;
- no generation start from Preflight review;
- no hidden cross-provider failover;
- database schema remains 23.

Next phases:

- A7.1 — Language Lock & Provider Language Enforcement
- A7.2 — Short-Utterance & Pronunciation Hardening
