# Phase 83 — Evidence Integrity Foundation & Technical-Debt Consolidation

## Goal

Phase 83 begins the post-certification architecture-cleanup track. It introduces no new production mutation, routing, billing, release, or governance behavior. Instead, it consolidates common tamper-evident evidence primitives that were duplicated across the Phase 80–82 operational services.

## Shared foundation

`app/services/evidence_integrity.py` now owns the common implementation for:

- SHA-256 file digests
- deterministic JSON payload digests
- safe JSON dictionary read/write
- service-specific safety-contract verification
- privacy scanning using each service's existing regex policy
- safe ZIP/archive entry names
- UTC-normalized timestamps

The mixin intentionally calls each subclass's existing `_safety_contract`, `_SECRET_RE`, and `_ABSOLUTE_PATH_RE`. This preserves the policy owned by each operational service while eliminating repeated mechanics.

## Migrated services

Phase 83 migrates a deliberately small first cohort:

1. `OperationsCommandCenterService` (Phase 80)
2. `EvidenceRefreshService` (Phase 81)
3. `OperationalReadinessCertificationService` (Phase 82)

Their existing private helper names remain available through inheritance, so current callers and tests do not need a compatibility shim.

## Safety / scope

This is a behavior-preserving refactor. Phase 83 does not:

- deploy, rollback, restart, publish, tag, or modify production
- change provider routing or provider configuration
- change billing or ledger state
- alter incident tickets
- weaken privacy checks or SHA verification
- change existing evidence schemas or artifact locations

Future cleanup phases may migrate older Phase 62–79 services only after this foundation passes the full regression suite.
