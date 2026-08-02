# Generation Launch Baseline Guard UX — Phase 38

## Goal

Phase 38 turns the Phase 37 receipt baseline into an active pre-launch safety control. A project can protect selected launch categories and decide whether drift should be informational, explicitly acknowledged, or blocked when critical.

## Project guard modes

- **Off**: no baseline comparison is added to launch review.
- **Warn**: protected critical or warning drift adds a required `baseline_drift_guard` acknowledgement.
- **Enforce**: protected critical drift blocks launch before the generation controller starts. Protected warnings still require acknowledgement.

The default for a project with no stored policy is **Warn** with all supported categories protected.

## Protected categories

- Provider
- Output format
- Output policy
- Execution
- Scope
- Risk and cost
- Integrity

Review-only receipt metadata is intentionally excluded from the recommended defaults so a previous acknowledgement does not create artificial launch drift.

## Launch integration

`GenerationConfirmationCoordinator.evaluate()` keeps its existing two-argument contract and accepts optional launch-guard context:

- `receipt_service`
- `project_name`
- `output_dir`

When supplied by `MainWindow.start()`, the coordinator builds a secret-free current launch preview and evaluates it against the trusted project baseline. The resulting guard state is rendered in the existing Phase 35 launch checklist.

## Policy storage

Policies are stored in:

```text
reports/generation-launch-guard-policies.json
```

Only project name, mode, protected category names and update time are persisted. API keys, credentials, source text and receipt payloads are not copied.

## UI

The Launch Receipts audit center adds:

- baseline guard policy status
- a **Baseline guard policy** action
- a responsive policy dialog using the shared Dialog Workspace components
- recommended-default restoration
- explicit category selection and mode descriptions

## Compatibility

- No database migration; schema remains 22.
- Existing calls to `GenerationConfirmationCoordinator.evaluate(state, settings)` remain valid.
- Projects without a baseline continue normally and receive an informational checklist row.
- Phase 35 acknowledgements, Phase 36 receipt integrity and Phase 37 baseline comparison remain intact.
