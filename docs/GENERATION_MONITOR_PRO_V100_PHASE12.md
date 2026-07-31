# Generation Monitor Pro v1.0 — Phase 12

## Problem Management & Known Errors

Phase 12 converts repeated generation incidents into durable known problems. It closes the gap between post-incident review and prevention by documenting workarounds, permanent fixes, recurrence, ownership, and linked corrective actions.

## Data model

Migration version 12 adds:

- `generation_known_problems`
- `generation_problem_incidents`
- `generation_incidents.problem_id`
- `generation_incidents.problem_status`
- `generation_incident_action_items.problem_id`

A pre-migration backup is created automatically with the `.pre-v12.bak` suffix.

## Known-problem lifecycle

Supported statuses:

1. `investigating`
2. `known_error`
3. `fix_planned`
4. `monitoring`
5. `closed`

Moving to `known_error` requires a documented workaround. Moving to `monitoring` or `closed` requires a documented permanent fix.

## Incident grouping and recurrence

A known problem can be created from one or more incidents belonging to the same project. The service aggregates:

- Error fingerprints
- Root-cause category
- Incident IDs
- Total occurrences
- First and last seen timestamps
- Highest severity
- Dominant owner

New incidents are compared with active known problems from the same project. An exact error fingerprint is automatically linked. Recurrence creates a Notification Center entry, Activity Timeline event, and incident update. A closed problem is reopened when the same failure returns.

## Corrective actions

Corrective actions created by post-incident reviews retain their incident relationship and can also be linked to the known problem. Existing actions are automatically linked when their incident is grouped into a problem.

## User interface

The Reports menu and Command Palette include **Problem Center**. The Problem Center supports:

- Project, status, category, and text filters
- Known-problem details and linked corrective actions
- Creation from one or more incident IDs
- Manual incident linking
- Owner, status, category, workaround, permanent-fix, and monitoring-date editing
- JSON and CSV export

The Incident Center also exposes **Create problem** and **Problem Center** actions and displays the current problem ID and status.

## Export

JSON and CSV exports contain:

- Problem identity and lifecycle status
- Fingerprints and linked incidents
- Occurrence counts and timestamps
- Workaround and permanent fix
- Ownership and root-cause category
- Linked corrective actions

Incident exports now also include `problem_id` and `problem_status`.

## Validation

Phase 12 adds tests for:

- Migration and backup
- Incident and corrective-action linking
- Lifecycle validation
- Automatic recurrence matching and notification
- JSON and CSV export
- Problem Center filtering and selection
