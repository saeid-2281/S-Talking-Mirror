# Roadmap 2 / B8.2B Stage 3B-2 — Bounded queue-restore pass

## Evidence and scope

Stage 3B-1 Windows acceptance recorded a smaller startup interval, but a GUI stall
sample during JobRepository.list_by_project -> JobRecord.from_row remained.
The original project restore path hydrated every record/job twice when output_dir
was supplied, regardless of whether the missing-output cleanup changed anything.
The load_csv path rendered the same queue in reset_row_range_controls and again
explicitly immediately afterward.

## Changes

- Rehydrate a project once when there are no missing *completed* output files.
  Keep reset_interrupted before reading; preserve the legacy missing-output
  reset transaction and second full read when at least one completed output
  path is missing. The public reset_missing_completed_outputs API is unchanged.
- Suppress the redundant early render/monitor/dashboard/preflight refresh only
  within load_csv. Range state and summaries are still computed and load_csv
  performs its normal single render, monitor refresh, preflight invalidation,
  dashboard refresh and status update at the end. Other range/close handlers
  use the prior refresh=True behavior.
- No filesystem sweep, DB schema, rendering architecture, generation control,
  account, migration, provider, language or credential change.

## Boundaries

This is a conservative improvement, **not** asynchronous CSV parsing or DB
hydration. It does not establish that the earlier 8-minute project switch was
fixed; a controlled Windows runtime comparison and separate investigation of
remaining stall sites are required. Source/Portable queue configurations must
be compared under the same Model/View configuration.

## Gate

Runner validates exact original HEAD+branch, preserved B7 and prior stage hashes,
all local files, internal ZIP member allowlist and SHA-256, then applies only
four files. Runs compile, Ruff, six dedicated tests, focused regressions and
Full Quality Gate; no commit, push or Portable build.
