# Phase 95 — Project / Session Workflow 2.0

Phase 95 adds a read-only Project Continuity layer over S-Talking's existing project, queue, batch-history and session-restore persistence.

## Product workflow

- Continue the last saved project session explicitly.
- Review recent projects with saved queue counts and latest run state.
- Review recent generation runs for a selected project.
- Open the latest completed audio, run output directory or report directly.
- Preserve the existing project open/load/queue-restore behavior.

## Safety and persistence contract

Phase 95 does **not** add a database migration or a second session format. `SessionRestoreService` remains authoritative for last-session UI state, ProjectManager/ProjectController remain authoritative for `.stproj` operations, the jobs table remains authoritative for saved queue state, and `batch_sessions` remains authoritative for recent run history.

Opening Project Continuity is read-only. Continuing a project never starts generation, retries jobs, changes queue order, or bypasses recovery/preflight. Generation Safe Resume remains the only run-resume workflow.
