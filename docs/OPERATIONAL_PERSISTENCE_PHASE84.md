# Phase 84 — Database & Persistence Consolidation

Phase 84 introduces a gradual, backward-compatible operational persistence layer.

## Goals

- Keep existing JSON and ZIP operational evidence authoritative.
- Add a normalized SQLite index for verified operational evidence.
- Preserve tamper-evident SHA-256 metadata and canonical payload digests.
- Store portable artifact filenames rather than workstation paths.
- Make synchronization explicit, append-only, and safe to repeat.
- Reject private material and evidence-key collisions.

## Schema

Migration 23 adds `operational_evidence_records` and `operational_persistence_runs`.
The evidence table stores source identifiers, evidence type, source service, portable artifact filename,
artifact SHA-256, canonical payload SHA-256, record SHA-256, status, schema version, project ID,
source timestamp, persistence timestamp, and canonical JSON payload.

## Initial synchronized sources

Phase 84 intentionally starts with the consolidated operational layer from Phases 80–82:

1. Production Operations Command Center snapshot.
2. Evidence Freshness Registry.
3. Certification Refresh record.
4. Operational Readiness snapshot.
5. Operational Readiness attestation.

Future phases can add more verified adapters without changing the persistence contract.

## Safety contract

The database is a secondary index, not a replacement for exported evidence. Synchronization does not:

- mutate or delete source artifacts;
- deploy, restart, publish, route providers, or alter billing state;
- store local absolute paths;
- automatically synchronize on startup.

## CLI

Status:

```powershell
.\scripts\operational-persistence.ps1
```

Explicit verified synchronization:

```powershell
.\scripts\operational-persistence.ps1 -Sync
```

Full database verification:

```powershell
.\scripts\operational-persistence.ps1 -Verify
```
