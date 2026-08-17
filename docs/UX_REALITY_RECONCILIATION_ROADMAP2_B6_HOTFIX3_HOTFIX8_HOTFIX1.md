# Roadmap 2 B6 Hotfix 3 — Hotfix 8 Hotfix 1

## Purpose

Hotfix 8 intentionally projects the rendered Dark QSS foundation from the historical navy family onto the selected Soft Professional surface family. Qt style-sheet polishing therefore exposes the projected canvas through `QWidget.palette()` on live widgets even though `ThemeManager.tokens("Dark")` and `ThemeManager.palette("Dark")` remain historical compatibility APIs.

The first Hotfix 8 run stopped in a Phase 25 regression because that older test treated the live widget palette and the ThemeManager API palette as byte-identical contracts. That assumption is no longer true after presentation projection and prevented the pixel-level certification from running.

## Contract reconciliation

- `DARK_TOKENS` remains unchanged, including historical `app == #0B1220`.
- `ThemeManager.palette("Dark")` remains built from those historical tokens.
- `ThemeManager.stylesheet("Dark")` remains presentation-projected to Soft Professional Dark.
- A live Dark widget may report the final style-sheet-polished Soft Professional canvas through `QWidget.palette()`.
- Light behavior is unchanged.
- System continues to resolve through ThemeManager; if its effective theme is Dark, the same rendered projection applies.
- No provider, account, routing, Preflight, Generation, credential, portable, or database authority changes.

This is a test-contract reconciliation only. Hotfix 8 production/runtime bytes are unchanged.
