# Roadmap 2 A7.7 — Launch Assurance Consolidation

## Purpose

A7.7 closes the gap between an explicit Preflight decision and the actual generation start. The launch path now fails closed unless the resolved generation request remains identical across all three checkpoints:

`Preflight Context == Launch Context == Generation Context`

A7.7 does **not** add routing or generation authority. It verifies context identity only.

## Canonical request revision

`PreflightService.request_revision(...)` is the single request-revision function used by Preflight and launch assurance. The revision covers the generation jobs, settings, output/source/project identity, account key fingerprint, and explicit per-job overrides.

A7.7 extends each job's canonical Preflight key with:

- explicit provider override
- explicit voice override
- explicit model override
- explicit language override
- explicit pronunciation decision

The existing settings payload already carries provider/account/voice/model/language, pronunciation dictionary selection/locators, generation scope, execution order, and other generation settings.

## Three fail-closed checkpoints

1. **Preflight → confirmation** — the current resolved request must still equal the explicit Preflight revision before launch evaluation.
2. **Launch review** — the request is checked again immediately before and immediately after explicit launch review/acknowledgement.
3. **Generation start** — the live request and the immutable Preflight evidence snapshot are checked immediately before the generation controller is allowed to start.

Any mismatch invalidates Preflight and returns the UI to **Preflight required**. A7.7 never silently reruns Preflight.

## Preflight evidence snapshot

Launch assurance binds the request revision to privacy-safe Preflight evidence including:

- estimated files / characters / provider requests
- estimated cost
- provider/output readiness
- quota snapshot
- generation plan
- language assurance evidence
- pronunciation current/stale/legacy/original/normalized evidence

The evidence is hashed for comparison. It is not a new source of provider or generation decisions.

## Failure semantics

If context changes before generation:

- generation does not start;
- Preflight is invalidated;
- the user is told to run Preflight explicitly again;
- any budget reservation created during the aborted launch is released;
- an initialized execution session is cancelled rather than silently continued.

## Authority invariants

A7.7 preserves all existing authority boundaries:

- user-selected target language remains authoritative;
- per-job explicit language override remains authoritative;
- no content-based language detection override;
- no automatic provider/account/voice/model/language changes;
- no automatic Preflight;
- no automatic generation;
- no automatic Smart Routing apply;
- no hidden cross-provider failover;
- no source text mutation.

The launch-assurance service does not create providers, call synthesis, mutate decisions, run Preflight, or start generation.

## Persistence

Database schema 23 is unchanged. A7.7 adds no migration and no new database persistence contract.

## Next fixed roadmap step

After successful A7.7 verification, continue with **A7.8 — Track A End-to-End Product Acceptance**.
