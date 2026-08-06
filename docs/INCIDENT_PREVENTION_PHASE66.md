# Phase 66 — Problem Management, Recurrence Analysis & Preventive Actions

Phase 66 turns verified Phase 65 closure records into a privacy-safe operational-learning baseline without changing any closed incident or automatically executing remediation.

## Purpose

The workflow verifies the complete closure → resolution → triage case → support-bundle custody chain, restricts analysis to a configurable lookback window, groups incidents by the deterministic Phase 64 fingerprint, scores recurrence risk and creates two local tamper-evident records after explicit human acknowledgement:

1. an incident prevention baseline;
2. an open preventive-action register.

## Analysis policy

- lookback window: 7–3650 days;
- recurrence threshold: 2–20 verified closures with the same fingerprint;
- high-risk threshold: 50–100;
- priority, recurrence and recency contribute to a deterministic 0–100 risk score;
- invalid or tampered closures are rejected;
- verified closures outside the selected lookback are ignored and reported;
- at least one in-scope verified closure is required.

## Privacy and integrity

The baseline stores only filenames, SHA-256 values, closure/case identifiers, deterministic fingerprints, categorical component and resolution type, timestamps, priorities and counts. Support logs, incident summaries, resolution narratives, customer-impact text, databases, settings and credentials are never copied.

The baseline and action register have independent SHA-256 signatures. Baseline verification revalidates every referenced Phase 65 closure and the complete source custody chain.

## Manual-operation contract

Every preventive action is created with `status: open` and `automatic: false`. Phase 66 never creates an external ticket, schedules work, applies a patch, deploys, rolls back, restarts, publishes knowledge or marks an action completed. Execution and completion evidence require a separate human-controlled workflow.

## User interface

Open **Reports → Incident Prevention & Recurrence**. Select closure certificates, review lookback and thresholds, inspect risk patterns and gates, then explicitly acknowledge creation of the local baseline and action register.

## PowerShell

Use `scripts/incident-prevention.ps1` to create or export snapshots, create acknowledged baselines, and verify baseline or register integrity.
