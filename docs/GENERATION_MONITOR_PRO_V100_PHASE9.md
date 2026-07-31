# Generation Monitor Pro v1.0 — Phase 9

## Incident Ownership, SLA & Escalation

Phase 9 turns the Incident Center into an accountable response workflow. Active incidents can be assigned to an owner, tracked against configurable response and resolution targets, escalated when deadlines are missed, and documented with an incident-specific update history.

## Ownership and incident updates

Each incident now stores an optional owner and operational priority. The Incident Center supports assignment, unassignment, and free-text notes. Assignment changes, notes, lifecycle transitions, occurrences, reopen events, and SLA escalations are persisted in `generation_incident_updates` and remain available after the project is reopened.

## SLA policies

A global policy provides default response and resolution targets. Projects may override it independently. Policies include:

- enable or disable SLA tracking
- critical response time
- critical resolution time
- warning response time
- warning resolution time

Saving a policy recalculates deadlines for active incidents in the selected scope.

## SLA states and escalation

Active incidents are evaluated as:

- On track
- Response overdue
- Resolution overdue
- Not configured

Resolved or dismissed incidents retain a final SLA result of Met or Breached. Missing the response target raises escalation level 1. Missing the resolution target raises escalation level 2. Each level generates at most one Notification Center entry, preventing repeated notifications when the Incident Center is refreshed.

Acknowledging an incident stops response-target escalation while preserving the resolution deadline. Reopening an incident starts a fresh SLA window and resets escalation state.

## Incident Center integration

The Incident Center retains its eight-column layout for regression compatibility while adding:

- SLA-state filter
- owner, due time, and escalation information
- assignment and note actions
- SLA policy editor
- SLA and update-history details
- summary counts for unassigned, overdue, and escalated incidents
- JSON and CSV exports containing ownership, SLA, escalation, and update history

Opening or refreshing the Incident Center evaluates active SLA deadlines and emits only newly reached escalation levels.

## Database

Migration version 9 adds ownership and SLA fields to `generation_incidents`, creates `generation_incident_sla_policies`, and creates `generation_incident_updates`. Existing migration behavior creates a `.pre-v9.bak` backup before upgrading an older project database.
