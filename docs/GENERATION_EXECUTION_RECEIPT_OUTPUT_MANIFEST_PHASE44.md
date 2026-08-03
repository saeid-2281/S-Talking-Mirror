# Generation Execution Receipt & Output Manifest — Phase 44

Phase 44 closes the gap between the launch plan and the files that were actually produced.
Every finalized generation run now receives an integrity-protected execution receipt and a
CSV output manifest linked to its run ID, launch receipt, execution session and final report.

## Artifacts

Each finalized run writes the following files inside its existing run folder:

```text
reports/<project>/runs/<run-id>/generation-execution-receipt.json
reports/<project>/runs/<run-id>/generation-execution-receipt.md
reports/<project>/runs/<run-id>/output-manifest.csv
```

The execution session is updated with the receipt ID and both artifact paths.

## Planned versus actual

The receipt preserves the launch plan where available:

- planned files
- planned characters
- planned provider requests
- outputs that existed before the run

Each expected job is classified as one of:

- `created`
- `overwritten`
- `skipped_existing`
- `skipped`
- `failed`
- `missing`
- `incomplete`

Files with the configured output extension that appear during the run but are not part of
the expected job set are recorded as `unexpected`.

## Output evidence

Existing output files include:

- size in bytes
- modification timestamp
- SHA-256 digest
- provider, model and voice used
- retry count and duration
- error code and error fingerprint when applicable

Source text and API credentials are never stored in the execution receipt or catalog export.

## User interface

The Reports menu, toolbar overflow and command palette include **Execution Receipts**.
The audit center supports project and status filters, free-text search, planned-versus-actual
summary metrics, manifest inspection and direct access to the linked session, launch receipt,
final report and output folder.

The existing Execution Sessions dialog also exposes the linked execution receipt and output
manifest.

## Compatibility

- Database schema remains version 22.
- Existing Phase 43 execution sessions load without receipt metadata.
- Existing launch receipts and generation reports are unchanged.
- Receipt and manifest creation failures are logged without preventing session finalization.
