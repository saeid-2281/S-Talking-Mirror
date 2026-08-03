# Generation Launch Approval Operations UX — Phase 40

## Goal

Phase 40 turns baseline guard exceptions into an operational workflow rather than a single launch-time dialog. Operators can search, inspect, renew, revoke and export approvals while preserving immutable history.

## Approval Operations Center

The center is available from:

- Reports → Approval Operations
- Toolbar overflow → Approval Operations
- Command Palette → Reports: Approval Operations
- Generation Launch Receipts → Approval operations

It supports project, lifecycle-state and full-text filters. Summary metrics cover total, active, expired, consumed and revoked approvals.

## Immutable renewal

Renewal never edits an existing approval. A new approval is created with `renewed_from_id`, a new expiry window and a fresh use allowance. The original record remains available for audit.

## Audit trail and launch linkage

Approval records now retain lifecycle events for creation, renewal, consumption and revocation. Consumption events can include the launch receipt ID. The operations center also discovers launch receipts that reference each approval.

## Export

Filtered approval records can be exported to JSON and CSV. Exports contain approval metadata, lifecycle state and counts but never API keys, credentials or source text.

## Compatibility

- Existing Phase 39 approval records without lifecycle events remain readable.
- Existing service calls remain valid; new filters and receipt IDs are optional.
- No database migration is required. Database schema version remains 22.
