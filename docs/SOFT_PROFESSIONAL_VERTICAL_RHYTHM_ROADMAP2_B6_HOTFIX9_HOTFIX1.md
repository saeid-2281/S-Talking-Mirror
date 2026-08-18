# Roadmap 2 B6 Hotfix 3 — Hotfix 9 Hotfix 1

## Purpose

The first Hotfix 9 run exposed a real Windows/PySide6 geometry defect before any commit or Full Quality Gate.  Even with Batch plan collapsed, the optional queue range frame could retain layout height and leave a 51 px blank slot between the queue heading and the Filters/Actions command rows.

## Repair

- The collapsed batch range frame now has **zero layout authority**: minimum height 0, maximum height 0, fixed vertical policy, hidden.
- Explicitly opening **Batch plan** restores exactly one compact row (`34 px control + 8 px vertical inset = 42 px`).
- Compact responsive mode always collapses the range row; returning to wide/standard restores it only if Batch plan is still explicitly expanded.
- Queue heading is fixed at 46 px, preserving the historical A9.1 46–56 px compatibility contract.
- The H9 vertical envelope assertion is corrected from an impossible 190 px threshold to a strict but attainable 220 px bound. With a 44 px launch band, 46 px heading, two 34 px command rows, 30–32 px summary and compact gaps, 190 px could never be satisfied even with zero dead space.

## Authority freeze

Presentation only. No provider/account/voice/model/language auto-switch, Preflight, Generation, Smart Routing, credential, portable-runtime, or database authority is changed. Database schema 23 is preserved.
