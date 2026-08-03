# Generation Launch Guard Approval UX — Phase 39

Phase 39 adds a controlled exception workflow to the project baseline guard introduced in Phases 37 and 38.

## Goals

- Keep `enforce` mode strict by default.
- Allow an authorized operator to approve one exact blocked launch without weakening the project policy.
- Bind approval to the current project, trusted baseline, protected change set, and launch fingerprint.
- Preserve a secret-free, reviewable audit trail.
- Consume approval capacity only after a launch receipt is written successfully.

## Approval contract

Each approval stores only:

- approval ID
- project name
- launch fingerprint
- baseline receipt ID
- protected change keys
- reason and approving operator
- creation and expiry times
- maximum and used launch counts
- lifecycle status

API keys, provider credentials, source text, and generated audio are not copied into the approval index.

## Lifecycle

- `approved`: valid, unexpired, and with remaining uses
- `expired`: expiry time has passed
- `consumed`: all authorized uses have been recorded
- `revoked`: manually disabled from the approval archive

An approval matches only when the project, baseline receipt, SHA-256 launch fingerprint, and complete protected change set are identical.

## Launch integration

When `enforce` mode blocks critical protected drift, the application opens the exception approval workflow. After a valid approval is created, preflight is evaluated again. A matching approval changes the result from blocked to confirmation-required and adds the required acknowledgement `baseline_drift_exception`.

The final launch receipt records the approval ID and target metadata inside the integrity-protected JSON. The approval use count is incremented only after both JSON and Markdown receipts have been written.

## User interface

The approval dialog supports:

- exact blocked-target preview
- approver and reason fields
- 15-minute, 1-hour, 4-hour, or 24-hour expiry
- one to ten authorized uses
- searchable project-scoped archive through Launch Receipts
- manual revocation and Approval ID copy

## Compatibility

- No database migration
- Database schema remains 22
- Existing receipts without approval metadata remain readable
- Existing baseline and guard policy files remain unchanged
- Public MainWindow handles and established button texts are preserved
