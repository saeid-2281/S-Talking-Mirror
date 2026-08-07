# Phase 81 — Automated Evidence & Certification Refresh

Phase 81 introduces a read-only evidence freshness registry and certification refresh record.

## Goals

- Classify operational evidence as `fresh`, `due_soon`, `expired`, `missing`, or `blocked`.
- Recompute a certification view from verified evidence without mutating the source artifacts.
- Preserve SHA-256 custody from the operations command center through the refresh registry.
- Surface refresh work before operational evidence becomes stale.

## Safety contract

A refresh does **not** deploy, roll back, restart, publish, alter providers, alter billing, change tickets, or mutate source evidence. Machine-local profile data is never copied into refresh artifacts.

## Default freshness policy

- Production health: 30 days
- Incidents: 14 days
- SLO and capacity: 7 days
- Recovery: 30 days
- Provider governance: 14 days
- Financial audit: 30 days
- Reliability assurance: 30 days

## Outputs

Artifacts are written below `artifacts/evidence-refresh/`:

- freshness registries
- certification refresh records
- latest registry pointer
- latest certification pointer

All records contain SHA-256 integrity fields and portable filenames only.
