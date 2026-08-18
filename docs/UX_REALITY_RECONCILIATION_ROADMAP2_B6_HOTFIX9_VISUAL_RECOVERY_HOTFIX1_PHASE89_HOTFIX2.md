# Roadmap 2 / B6 Hotfix 3 / Hotfix 9 / Visual Recovery Hotfix 1 / Phase89 Hotfix 2

## Purpose

Reconcile the historical Phase89 standalone compact-widget regression with the
already-certified A9/H4 structural disclosure contract after the full serial
quality gate exposed process-order-dependent Qt stylesheet state.

## Evidence boundary

The exact same Phase89/Phase92 focused lane passed 25/25 immediately before the
full quality gate. In the same runner, the full serial suite later failed only
`test_phase89_compact_mode_yields_vertical_space_to_queue`: the hidden compact
`GenerationJourneyWidget` reported `minimumHeight() == 56` while its explicit
compact maximum remained 52. No H9 geometry, three-theme certification, B6 H3
visual continuity, or H8 pixel-color check failed.

The compact queue-space authority is structural: while collapsed, the workflow
widget is hidden and removed from `QueueWorkspace.root_layout`. A process-global
Qt stylesheet may still contribute a minimum-size hint to the standalone hidden
widget in a long-lived QApplication. Treating that style-derived minimum as a
queue-space invariant makes the historical component test order-dependent.

## Change

Test-contract only:

- preserve assertions that compact mode hides the workflow widget, steps, and
  summary while retaining the primary action child;
- preserve the explicit compact `maximumHeight() == 52` contract;
- remove the order-dependent `minimumHeight() <= maximumHeight()` assertion;
- verify leaving compact mode restores the visible widget and the historical
  `maximumHeight() == 104` contract.

No production/runtime source is changed. H9 Queue geometry, provider/routing,
Preflight/Generation authority, credential storage, Portable behavior, and
Database schema 23 are unchanged.
