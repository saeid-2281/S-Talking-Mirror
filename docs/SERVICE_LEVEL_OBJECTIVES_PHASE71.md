# Phase 71 — Service-Level Objectives, Error Budget & Release Safety

Phase 71 adds a human-controlled reliability workflow for the stable 1.0 release. It combines privacy-safe operational observations with verified Phase 70 continuity evidence, calculates service-level objectives and availability error-budget burn, and records a tamper-evident human release-safety decision.

## Workflow

1. Create or select one or more human-reviewed operational observation files.
2. Select matching Phase 70 continuity result, attestation, audit-pack and receipt files.
3. Define the SLO window, availability target, success target and P95 latency target.
4. Review source custody, coverage, objective and error-budget gates.
5. Export a signed SLO snapshot.
6. Record a human decision: `allow`, `manual_review` or `hold`.
7. Retain the generated snapshot, decision, audit pack and receipt.

## Calculations

- Availability is calculated from observed window minutes and unavailable minutes.
- Operation success is calculated from successful operations divided by total operations.
- P95 latency uses the most conservative maximum P95 across selected observations.
- Availability error budget is derived from the selected availability target and observed minutes.
- A burn rate of 0.8 or greater requires manual review; a burn rate above 1.0 blocks release approval.

## Safety contract

Phase 71 never performs any of the following automatically:

- Deploy or publish a release
- Roll back a release
- Restart the application or operating system
- Make a release decision
- Upload evidence
- Include credentials, secrets or local absolute paths in human statements

Every generated JSON document has a canonical SHA-256 digest. The audit pack contains a signed manifest and a separate receipt containing the ZIP filename, size and SHA-256.

## User interface

Open **Reports → Service-Level Objectives & Error Budget**.

## PowerShell

Use `scripts/service-level-objectives.ps1` to create observations, export snapshots, create release-safety decisions and verify evidence. Evidence creation requires `-Acknowledge`.
