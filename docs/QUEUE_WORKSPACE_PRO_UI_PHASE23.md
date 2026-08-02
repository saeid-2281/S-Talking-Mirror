# Queue Workspace Professional UI — Phase 23

Phase 23 refreshes the main S Talking workspace without changing generation,
queue or provider contracts.

## Goals

- Make project identity and readiness understandable at a glance.
- Give the generation action a clear visual priority.
- Keep dense operational data readable on 1366×768 and larger displays.
- Preserve existing public widget handles and keyboard-driven workflows.
- Make presentation choices part of workspace profiles rather than scattered UI state.

## Main workspace changes

### Project header

The workspace header now separates:

- project and source identity;
- provider and model context;
- preflight readiness;
- source and output actions.

Standard and Wide profiles show the expanded header. Compact, Generation,
Review and Debug use the compact header. Focus Mode hides the header and queue
metrics entirely.

### Queue metrics

Queue metrics are now individual semantic cards. Failed, active, completed and
warning states receive distinct emphasis while retaining the original clickable
status-filter behavior.

### Generation command dock

The bottom action row is now a command dock with:

- generation state badge;
- primary Start action;
- preflight action;
- pause and stop controls;
- current item and total progress context.

### Presentation controls

The View menu contains a Workspace presentation section:

- Focus queue (`Ctrl+Shift+F`)
- Show project header
- Show queue metrics
- Compact density
- Comfortable density

Density changes are persisted and update controls, queue rows, shell spacing and
the generation command dock together.

## Compatibility

The following handles remain stable:

- `window.project_context_bar`
- `window.csv`
- `window.out`
- `window.source_summary`
- `window.output_summary`
- `window.cards`
- `window.startb`
- `window.preflight_status`
- `window.pauseb`
- `window.stopb`
- `window.bar`

No database migration is required for Phase 23.
