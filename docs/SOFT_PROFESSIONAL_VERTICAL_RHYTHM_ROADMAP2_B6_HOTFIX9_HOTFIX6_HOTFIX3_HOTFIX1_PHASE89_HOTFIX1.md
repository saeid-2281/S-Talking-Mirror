# Roadmap 2 B6 Hotfix 3 / Hotfix 9 / Hotfix 6 / Hotfix 3 / Hotfix 1 / Phase89 Hotfix 1

## Scope

This is a test-contract-only continuation from the exact failed/uncommitted H9 chain after Runner Hotfix 1.
No production/runtime source is changed.

## Why the Phase89 assertion changed

The focused Phase89/Phase92 lane proved that the modernized queue disclosure chain is healthy, but the historical standalone `GenerationJourneyWidget` compact-mode test still required `minimumHeight() == 0` after the widget had already been shown and Qt had processed layout events.

With the current widget layout, the compact state intentionally keeps the primary action available internally while hiding the disclosure. Qt can therefore expose the compact primary-action row plus the widget's vertical margins as a non-zero minimum height (46px on the certified Windows lane). That value does not consume queue space because A9/H4/H6 physically detach the collapsed journey from `QueueWorkspace.root_layout`; those structural contracts are separately exercised by the H4/H6 and Phase89 MainWindow tests.

The historical test now preserves the meaningful compact contract:

- the journey is hidden while compact;
- the steps and summary are hidden;
- the primary action remains available for explicit focus/reveal;
- the widget remains bounded by the existing 52px compact ceiling;
- leaving compact mode restores the remembered presentation state.

The test does not relax any queue-layout acceptance threshold. H9's `<=220px` launch-to-summary envelope, H6H3 top anchoring, fixed chrome, canonical disclosure ordering, System/Light/Dark certification, Track A authority, and database schema 23 remain unchanged.
