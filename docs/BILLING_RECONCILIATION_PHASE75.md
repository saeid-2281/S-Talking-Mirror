# Phase 75 — Provider Billing Reconciliation & Dispute Readiness

Phase 75 adds a local, human-reviewed workflow for comparing provider invoice totals with S-Talking usage evidence after a verified Phase 74 recovery replay.

## Normalized invoice input

The invoice importer accepts a UTF-8 CSV with these required columns:

- `line_id`
- `request_id`
- `amount`

Optional columns are `quantity` and `usage_type`. The normalized record hashes line and request identifiers, stores reviewed totals, and never embeds the original provider invoice or its local path.

## Reconciliation evidence

The service verifies matching Phase 74 result, attestation, audit pack and receipt files. A reviewer then records internal ledger totals, provider credits, matched requests, missing requests, unexpected requests and confirmed duplicate charges.

A verified result requires all reviewed thresholds to pass. A failed comparison is preserved as `withheld` and produces a local dispute-readiness pack for manual review.

## Safety contract

Phase 75 never requests a refund, submits a dispute, emails a provider, uploads evidence, changes billing, changes queue state or makes a release decision automatically. The dispute pack is local evidence only and requires a human decision outside the application.

## CLI

Use `scripts/billing-reconciliation.ps1` to inspect current readiness. The frozen CLI also supports importing a normalized invoice, verifying evidence and recording a reviewed result.
