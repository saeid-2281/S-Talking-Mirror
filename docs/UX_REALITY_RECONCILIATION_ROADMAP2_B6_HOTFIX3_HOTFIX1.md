# Roadmap 2 B6 Hotfix 3 — Hotfix 1

## Purpose

Restore the A11.1 Generation Monitor usable-width contract after B6 Hotfix 3.
The UX reconciliation patch was applied successfully, but the focused compatibility
lane exposed a Qt dock-layout race: the active Generation Monitor could be reset to
the historical 290 px geometry by `MainWindow.resizeEvent()` after the visual
fidelity hardener had requested the 340 px presentation width.

## Repair

- Publish `visualFidelityRequestedWidth` before dock geometry changes.
- Make `MainWindow.clamp_monitor_width()` honor that requested width only while the
  Generation Monitor tab is active.
- Preserve the historical public `minimumWidth()` contract around 290 px.
- Keep the monitor capped at 340 px and keep Selected Row behavior unchanged.
- Add a regression that survives a real main-window resize event.

## Authority boundary

Presentation geometry only. No provider/account/voice/model/language switching,
Preflight, Generation, Smart Routing, recovery, output, B6 operations, credential,
portable-runtime, or database-schema authority changes are introduced.
