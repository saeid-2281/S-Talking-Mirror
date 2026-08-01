# Queue Orchestration — Phase 21

## Queue Operations Center & UI Upgrade

Phase 21 turns the orchestration dialog into an operator-focused workspace while preserving every Phase 17–20 policy and telemetry surface.

### UI improvements

- Structured header, project badge and contextual subtitle.
- Four KPI cards for provider health, circuit state, concurrency and deadline risk.
- Recommended-action banner derived from live orchestration telemetry.
- West-side navigation to reduce horizontal tab crowding.
- Overview table combining health, circuit and throttle state per account.
- Shared search and operational filters across all tables.
- Compact and comfortable table density.
- Optional auto-refresh with a configurable interval.
- Persisted per-project UI preferences.
- Clear primary actions and consistent card/table styling.

### Operational presets

- Safe / serial
- Balanced
- High throughput
- Deadline protection

Presets update failover, adaptive routing, scheduling and deadline policy baselines. Individual controls remain editable after applying a preset.

### Persistence

Migration 21 adds `generation_orchestration_view_preferences`, keyed globally or by project. No credentials are stored.
