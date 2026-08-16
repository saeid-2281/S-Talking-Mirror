# Roadmap 2 B3 — Intelligent TTS Run Ledger & Outcome Reconciliation

## Certified baseline

B3 starts from the successful B2 + Hotfix 3 commit:

`6ee5b9710e27ab6fd302a0d0ab21fd32d10bf659`

B1 manifest authority, B2 execution binding, the System / Light / Dark visual
contract and the Dark Theme surface correction are frozen inputs.

## Why B3 exists

B1 gives every planned TTS request a deterministic production identity. B2
verifies that identity immediately before the existing
`GenerationController.start(...)` boundary. B3 makes that identity durable
through the complete run lifecycle without taking execution authority.

## Durable run ledger

`IntelligentTTSRunLedgerService` writes a privacy-safe JSON ledger after the B2
binding is verified and before the existing generation start call. It preserves
run/project identity, manifest and authority digests, request ids and order,
provider/profile/voice/model/language, output root, lifecycle events and final
execution-session / execution-receipt / report links.

Each event is SHA-256 chained to the prior event and the complete ledger has its
own digest. Persisted tampering fails verification.

## Lifecycle

The ledger follows existing user/application lifecycle only:

- approved after B2 verification;
- running through the existing execution-session sync;
- paused/running/stopping from the existing controls;
- completed/partial/failed/cancelled from existing finalization.

No automatic start, retry, recovery or routing path is introduced.

## Outcome reconciliation

Terminal summary counts are compared with the B2 request count and recorded as
`exact`, `cancelled_unexecuted`, `partial_accounting` or `over_accounted`.
This is audit evidence only; B3 never fabricates or changes job outcomes.

## Privacy and authority freeze

The ledger never stores raw source text, API keys or arbitrary metrics. B3 does
not create/select providers, change account/voice/model/language, infer language,
run Preflight, start/restart Generation, apply Smart Routing, retry requests,
choose cross-provider recovery, reorder the queue or migrate Database schema 23.

## Evidence

Machine certification:
`artifacts/intelligent-tts-production/roadmap2-b3/`

Live ledgers:
`<reports_dir>/intelligent-tts-run-ledger/<project>/`

## Exit criteria

B3 closes after 16 ledger tests, 8 integration tests, certification, B1/B2 and
Generation/Track A/visual regressions, one Full Quality Gate, commit/push and a
clean source Working Tree excluding local-only profiles.

Next: **Roadmap 2 B4**.
