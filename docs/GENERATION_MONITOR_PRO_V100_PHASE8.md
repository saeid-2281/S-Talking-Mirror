# Generation Monitor Pro v1.0 — Phase 8

## Incident Center & Resolution Workflow

Phase 8 turns critical performance alerts into persistent operational incidents. Repeated regressions with the same project and alert fingerprint are grouped into one active incident instead of producing disconnected records.

## Automatic incident creation

A critical regression opens an incident when its alert is eligible to be emitted. The incident stores:

- project and stable alert fingerprint
- severity and lifecycle status
- first and latest affected session
- all related session identifiers
- occurrence count
- first-seen and latest-seen timestamps
- current regression summary
- acknowledgement and resolution timestamps
- optional resolution note

A duplicate critical regression inside the alert cooldown updates the existing active incident and links the new session to it. An acknowledged incident is reopened automatically when the same regression occurs again.

## Incident lifecycle

Incidents support these states:

- Open
- Acknowledged
- Resolved
- Dismissed

The Incident Center supports multi-row actions for acknowledgement, resolution, dismissal, and reopening. Lifecycle changes are propagated to every linked batch session and recorded in Activity Timeline.

## Incident Center

The Reports menu and Command Palette now expose a dedicated Generation Incident Center with:

- current-project scope
- status and severity filters
- full-text search across incident, fingerprint, session, summary, and resolution note
- occurrence count and latest-session overview
- detailed related-session view
- JSON and CSV export
- lifecycle actions for selected incidents

Critical regression notifications now open the Incident Center when an incident is created. Generation History exports include incident identifier and incident status, and session details show linked incident metadata.

## Database

Migration version 8 creates `generation_incidents`, adds incident linkage fields to `batch_sessions`, and creates indexes for project, status, fingerprint, and session lookup. Existing migration backup behavior creates a `.pre-v8.bak` file before upgrading an older project database.
