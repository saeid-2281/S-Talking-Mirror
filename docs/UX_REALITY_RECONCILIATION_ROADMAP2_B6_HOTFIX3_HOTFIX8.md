# Roadmap 2 B6 Hotfix 3 — Hotfix 8

## Legacy Dark Base Projection

Manual pixel evidence after Hotfix 7 Hotfix 2 narrowed the remaining visual failure to the main Dark shell:

- dark main legacy structural share: 9.2569%
- dark Provider Accounts legacy structural share: 0.3352% (already below the 1% acceptance threshold)
- Light legacy `#2563EB` primary share: 0.0000% (resolved)

The exact Dark Main diagnostics showed that the remaining pixels came from the historical Dark theme foundation rather than the newer component overlays:

- `#0B1220`: 7.0302%
- `#0F1B31`: 0.4827%
- `#1C2C46`: 1.7440%

These values originate in `app/gui/theme.py`, including the global `QWidget` background and older `palette(window/base/alternate-base/button)` rules. Because those rules apply to unnamed layout hosts, splitter gutters and secondary controls, component-specific overlays cannot reliably enumerate every leak.

Hotfix 8 therefore adds a presentation-only compatibility projection at `ThemeManager.stylesheet("Dark")`:

- historical public `DARK_TOKENS` remain unchanged;
- `ThemeManager.palette("Dark")` remains unchanged for historical tests/integrations and Light/Dark/System detection;
- only the returned Dark stylesheet is projected onto the selected Soft Professional semantic surface family;
- legacy canvas/app colors map to Soft Professional Dark canvas;
- legacy surface/raised/input/hover colors map to Soft Professional Dark surface or secondary surface;
- legacy structural border colors map to Soft Professional borders;
- background-oriented Qt palette references (`window`, `base`, `alternate-base`, `button`, `midlight`) are projected to semantic literals so unnamed widgets cannot reintroduce navy through the historical QPalette;
- Light and Graphite stylesheet bytes are unchanged;
- semantic state colors, generation/provider authority, credentials, portable behavior and database schema remain out of scope.

This is deliberately below the A8+ component overlays: the compatibility projection cleans the historical Dark foundation, while later Soft Professional component selectors remain the final visual authority.

## Acceptance

Hotfix 8 must pass:

1. dedicated compatibility-projection tests;
2. Hotfix 6/7 and B6 Hotfix 3 continuation regressions;
3. Provider Accounts / theme visual regressions;
4. Startup / HiDPI / performance compatibility;
5. fresh pixel-level System / Light / Dark certification with:
   - Dark Main legacy structural share < 1%;
   - Dark Provider Accounts legacy structural share < 1%;
   - Light legacy `#2563EB` primary share < 0.2%;
6. B6 operations / Track A authority smoke;
7. historical QProcess regression;
8. one Full Quality Gate before commit/push.

B7 remains blocked until the fresh screenshots also pass manual visual review.
