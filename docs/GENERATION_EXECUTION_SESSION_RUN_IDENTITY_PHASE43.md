# Generation Execution Session & Run Identity — Phase 43

Phase 43 connects the reviewed launch decision to the generation that actually runs.
Every successful start receives a unique `run_id` before provider work begins. The ID
is written into the launch receipt, the live execution session, the generation report,
the batch history record, activity metadata, and the user-visible status/log surface.

## Execution session record

Execution sessions are stored under:

```text
reports/<project>/runs/<run-id>/generation-execution.json
reports/<project>/runs/<run-id>/generation-execution.md
```

The record is secret-free and contains:

- project ID and project key
- launch receipt ID and path
- launch fingerprint and unified decision trace
- guard approval ID when an exception was used
- provider, model, voice, scope, order, and output directory
- lifecycle state and timestamps
- job rows, filenames, source references, statuses, retries, durations, and outputs
- final report path and monitor metrics

Source text and API credentials are never persisted. Error strings are sanitized before
writing. Every JSON session carries a SHA-256 digest; changed records load as `Mismatch`.

## Lifecycle

1. A unique run ID is allocated after launch review and before generation starts.
2. The launch receipt stores the run ID and expected session path.
3. A running session snapshot is created with the reviewed queue.
4. Progress, pause, resume, and stop requests update the same session.
5. Completion closes the session as `Completed`, `Partial`, `Failed`, or `Cancelled`.
6. The final HTML report path is linked back to the run.

No database migration is required. Database schema version remains 22.

## Execution Sessions center

Reports → Execution Sessions provides:

- current-project and lifecycle filters
- search by run, receipt, decision trace, provider, output, or filename
- run progress and integrity state
- linked launch receipt, report, output, and session JSON actions
- secret-free JSON and CSV catalog export

## Compatibility

Existing launch receipts remain readable. Older receipts have empty execution identity
fields and continue to appear in the Launch Receipts center without errors.
