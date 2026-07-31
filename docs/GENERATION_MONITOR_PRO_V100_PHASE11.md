# Generation Monitor Pro v1.0 — Phase 11

## Post-Incident Review & Corrective Actions

Phase 11 closes the incident-management loop by turning resolved incidents into structured learning records and tracked prevention work. Each incident can have one post-incident review and any number of corrective action items.

## Post-incident reviews

A review is created from the Incident Center and begins as a draft. The initial draft is prefilled with the incident impact count, inferred root-cause category, assigned owner, resolution note, and completed remediation names when available.

The review captures:

- impact summary
- root-cause category and detailed root cause
- contributing factors
- detection gap
- resolution summary
- lessons learned
- reviewer and completion timestamp

A review can only be completed after its incident is resolved or dismissed. Completion also requires the impact, root cause, resolution summary, and lessons-learned fields. Drafts remain editable, and completed reviews retain their audit timestamps.

## Corrective actions

Corrective actions are linked to the incident review and store:

- title and note
- owner
- priority from P1 to P4
- optional ISO-8601 due date
- Open, In progress, Completed, or Cancelled status
- completion and overdue-notification timestamps

Actions can be added, edited, started, completed, cancelled, reopened, or deleted from the review window. Changing a due date resets overdue notification state so a future missed deadline can be reported correctly.

## Due-date monitoring

Opening or refreshing the Incident Center evaluates active corrective actions. When an Open or In-progress action passes its due date, Phase 11:

- creates one warning in Notification Center
- records an incident update
- records an Activity Timeline event
- prevents duplicate overdue notifications for the same due date

## Incident Center integration

The Incident Center adds a Review action for one selected incident. Incident details now show:

- review status, root-cause category, and reviewer
- root cause and lessons learned
- corrective-action status, priority, owner, due date, and title

## Export

Incident JSON and CSV exports now include:

- the complete post-incident review
- all corrective actions and their audit fields
- overdue-notification timestamps

## Database

Migration version 11 creates:

- `generation_incident_reviews`
- `generation_incident_action_items`

Existing incidents, sessions, SLA data, runbooks, and remediations are preserved. Before upgrading an older project database, the database layer creates a `.pre-v11.bak` backup automatically.
