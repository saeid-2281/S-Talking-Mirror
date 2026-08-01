# Queue Orchestration — Phase 22

## Workflow UX, Saved Views & Operator Actions

Phase 22 turns the Queue Operations Center into a reusable operator workflow rather than a read-only telemetry surface.

### Saved workspaces

Operators can save a named combination of:

- active operations page;
- shared search query;
- operational status filter;
- compact or comfortable table density.

Saved workspaces are scoped per project, can be recalled instantly, and one workspace can be marked as the default. Keyboard shortcuts provide direct access to search, refresh, and saving the current workspace.

### Attention queue

A dedicated Attention page combines actionable operational risks from:

- open or half-open provider circuits;
- active rate-limit cooldowns;
- queue deadline forecasts in Watch, At Risk, or Missed state.

Critical items are shown first. Each row includes the issue, recommended response, supported operator action, and latest update time.

### Safe operator actions

The operations center can execute selected actions or all currently available safe fixes:

- reset a reviewed provider circuit;
- clear a recovered provider throttle/cooldown;
- apply the concurrency recommended by the latest queue forecast.

Every action is persisted in an audit history and optionally added to the Activity Timeline. Action failures are retained in metadata instead of being silently discarded.

### Persistence and export

Migration 22 adds:

- `generation_orchestration_saved_views`;
- `generation_orchestration_operator_actions`.

JSON and CSV orchestration exports now include saved views, attention items, and operator-action history. API credentials are never stored in these records.
