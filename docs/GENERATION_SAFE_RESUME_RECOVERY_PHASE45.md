# Generation Safe Resume & Recovery — Phase 45

Phase 45 adds a guarded recovery workflow for partial, failed, cancelled, missing-output, and incomplete generation runs.

## Goals

- Continue only the work that still needs attention.
- Never recover from a tampered execution receipt.
- Prevent accidental provider, model, voice, output-directory, output-mapping, or file-policy drift.
- Reuse the current project source text instead of storing source text in historical receipts.
- Route every recovery through the normal Unified Preflight Decision Engine, baseline guard, quota, provider readiness, and output-conflict checks.
- Link the child run to its parent run with an integrity-protected resume receipt.

## Recovery scopes

- `unresolved`: failed, missing, and incomplete outputs; recommended.
- `failed_only`: failed provider jobs only.
- `missing_only`: jobs marked complete whose expected output is missing.
- `incomplete_only`: jobs that never reached a terminal result.
- `entire_run`: every planned parent job; existing outputs remain subject to Skip/Overwrite policy.

Unexpected outputs are never selected automatically.

## Compatibility guard

Recovery is blocked when any of the following is true:

- Parent execution receipt integrity is not verified.
- The current project differs from the parent project.
- Provider, model, or voice differs.
- Output directory or per-row output mapping differs.
- Source character count changes after the recovery plan is created.
- Selected parent rows cannot be matched to the current queue.
- Existing selected outputs have neither Skip existing nor Overwrite enabled.
- The selected scope has no eligible jobs.

The current source is authoritative. The recovery receipt stores row numbers, filenames, dispositions, settings identifiers, and paths, but never source text, API keys, tokens, or credentials.

## Resume receipt

Preparing a recovery queue creates:

```text
reports/<project>/recoveries/<resume-id>/generation-resume.json
reports/<project>/recoveries/<resume-id>/generation-resume.md
```

The JSON receipt includes SHA-256 integrity metadata and records:

- Parent run and parent execution receipt.
- Recovery scope and selected rows.
- Compatibility warnings and recommendations.
- Provider, model, voice, output directory, and file policy.
- Status lifecycle: `planned`, `started`, then `completed`, `partial`, `failed`, or `cancelled`.
- Child `run_id` after generation starts successfully.
- Child execution receipt ID and path after the recovery run finishes.

## Run lineage

Phase 43 execution sessions and Phase 44 execution receipts now include:

- `parent_run_id`
- `resume_receipt_id`
- `resume_receipt_path`
- `resume_scope`

This provides an auditable parent-child chain without a database migration. Database schema remains version 22.

## UX

The Execution Receipt Center adds **Plan safe resume** for verified recoverable receipts. The preview dialog shows:

- Scope selector.
- Blocking compatibility issues.
- File-policy warnings.
- Selected and excluded candidates.
- Current-output existence.
- Explicit reminder that Unified Preflight and baseline guard run again before launch.

The prepared queue switches to Selected Rows scope. The user still starts generation through the standard Start Generation action.
