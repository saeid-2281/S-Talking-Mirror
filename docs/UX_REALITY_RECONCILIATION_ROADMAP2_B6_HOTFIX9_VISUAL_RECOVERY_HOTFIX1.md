# Roadmap 2 / B6 Hotfix 3 / Hotfix 9 / Visual Recovery Hotfix 1

## B6 H3 runtime continuity restoration

The isolated visual watchdog exposed a real production regression rather than a
stale test: `MainWindow._finish_deferred_startup` was absent. Comparing the H9
Hotfix 4 `main.py` payload against the certified B6 Hotfix 3 chain showed that
H9 Hotfix 4 had unintentionally replaced several previously certified runtime
UX repairs while adding structural Queue disclosure synchronization.

This hotfix restores the certified B6 Hotfix 3 through Hotfix 5 `MainWindow`
runtime behavior and keeps the single H9 presentation addition required by the
new Queue disclosure composition:
`main_workspace_modernizer.sync_queue_disclosure_layout_from_widgets()`.

Restored contracts include deferred first-paint startup/session recovery,
non-modal moved-project recovery via `ProjectPathNotice`, 24 px DPR-aware main
toolbar icons, readable runtime-font setup, and persistent Generation Monitor
visual-fidelity width authority. Provider/routing/Preflight/Generation,
credential storage, portable layout, and Database schema 23 authority are not
changed.

The original B6 H3 through H8 regression files are rerun in isolated pytest
processes before H9 geometry/theme certification and the single Full Quality
Gate. The existing `<=220px` H9 launch-to-summary envelope remains unchanged.
