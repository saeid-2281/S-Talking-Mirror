# Phase 65 — Incident Resolution, Closure & Knowledge Capture

Phase 65 completes the local production-incident evidence chain without changing the immutable Phase 63 support bundle or Phase 64 triage case.

## Purpose

The feature verifies a Phase 64 triage case and remediation plan, requires passed dedicated regression and full Quality Gate evidence, validates privacy-safe resolution text, and creates three tamper-evident local records:

1. an incident resolution record;
2. a human-approved closure certificate;
3. a knowledge note that remains unpublished until separate human review.

## Closure gates

Closure is blocked unless all of the following are true:

- the triage case and remediation plan pass SHA-256 verification;
- both records belong to the running stable application and the same case;
- the immutable triage case remains in the `open` state;
- the resolution summary and customer-impact statement contain no credential-like values or local user/project paths;
- exactly one signed `dedicated_regression` JSON and one signed `full_quality_gate` JSON are supplied for the same case;
- both evidence records report passed tests, zero failed tests and no private data;
- full Quality Gate evidence confirms compileall and Ruff passed;
- no verified closure already exists for the case;
- a human explicitly acknowledges closure creation.

## Evidence and privacy

Raw arbitrary logs, project sources, databases and settings are never copied into closure records. Accepted evidence is capped at 2 MB, must be JSON, must be tamper-evident, and is canonicalized to a small safe field set before being stored under `artifacts/incident-resolution/evidence`.

Resolution and customer-impact text is limited in length and rejected when it contains credential-like assignments, tokens, URL credentials, local home paths or project paths.

## Manual-operation contract

Phase 65 never deploys a fix, applies a patch, performs a rollback, restarts the application, closes an external ticket, sends a customer notification or publishes a knowledge article. Closure files explicitly record these operations as false. External communication, ticket state and publication remain separate human decisions.

## User interface

Open **Reports → Incident Resolution & Closure**. Select the verified Phase 64 case and plan, provide the two signed evidence JSON files, enter a privacy-safe resolution summary and customer impact, review all gates, acknowledge the workflow and create the local records.

## PowerShell

Use `scripts/incident-resolution.ps1` for snapshots, acknowledged closure creation and integrity verification of resolution, closure or knowledge files.
